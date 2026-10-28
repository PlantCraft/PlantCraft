"""The data of a diagram: every binding's value now, and the window behind it for playback.

One read serves a whole diagram: each binding is resolved like a card item (``query.cards``),
the numeric signals are read in one batch over the window (``POST /api/v1/series``) and the
apps' results about assets and signals give the states they publish. The page then moves a
cursor over that window without asking again.

Fail-safe: a binding that cannot be read keeps its place with ``error`` (the symbol greys out
and says why), and a value older than ``stale_seconds`` is ``stale`` with state ``unknown``:
an old number never shows as a healthy plant.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.client import PlantCraftError, Unauthorized

from dashcraft.dashboards.model import CardItem, window_seconds
from dashcraft.diagrams.model import Limits, bindings
from dashcraft.i18n import t
from dashcraft.query.cards import (
    Reader,
    Resolved,
    _batch,
    _value,
    read_result,
    resolve,
    trend_step,
)

# A value older than this is stale: drawn grey, never as normal.
STALE_SECONDS = 900


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _stamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def judge(slot: str, binding: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """What a value means for its slot: the state of a colour or a value, the fraction of a
    level, on or off for running and flow. The page does the same at each playback instant
    (``frontend/src/diagramModel.ts``)."""

    value = _number(row.get("value"))
    out: dict[str, Any] = {}
    if slot in ("state", "value"):
        if row.get("kind") == "result":
            out["state"] = row.get("state") or "unknown"
        else:
            limits = Limits.model_validate(binding.get("limits") or {})
            out["state"] = limits.state(value)
    elif slot == "level":
        low, high = float(binding.get("min", 0.0)), float(binding.get("max", 100.0))
        out["fraction"] = (
            None if value is None else min(1.0, max(0.0, (value - low) / (high - low)))
        )
        out["state"] = "unknown" if value is None else "ok"
    else:
        out["on"] = None if value is None else value > float(binding.get("above", 0.5))
        out["state"] = "unknown" if value is None else "ok"
    if row.get("error") or row.get("stale"):
        out["state"] = "unknown"
    return out


def read_diagram(
    reader: Reader,
    diagram: dict[str, Any],
    window: str | None = None,
    end: datetime | None = None,
    *,
    stale_seconds: int = STALE_SECONDS,
) -> dict[str, Any]:
    """Every binding's row and the window's series by signal.

    ``end`` set: a past period (playback of history); each value is then the last of the
    window's series, results show as they are now and say so (``history: false``).
    """

    window = window or diagram.get("default_window") or "1h"
    seconds = window_seconds(window)
    step = trend_step(seconds)
    live = end is None
    end = (end or reader.clock()).astimezone(timezone.utc)
    start = end - timedelta(seconds=seconds)
    resolved: dict[tuple[Any, ...], Resolved] = {}
    rows: list[dict[str, Any]] = []
    wanted: list[str] = []
    for element_id, slot, binding in bindings(diagram):
        try:
            item = CardItem.model_validate(binding.get("item") or {})
        except ValueError:
            rows.append(
                {
                    "element": element_id,
                    "slot": slot,
                    "label": "",
                    "error": t("This binding names no signal."),
                    "state": "unknown",
                }
            )
            continue
        base: dict[str, Any] = {"element": element_id, "slot": slot}
        if item.result is not None:
            found = read_result(reader, item, None, False)
            row = {**base, **found, "history": False}
        else:
            key = (item.signal_id, item.asset_id, item.role)
            if key not in resolved:
                resolved[key] = resolve(reader, item, None, False)
            one = resolved[key]
            row = {**base, **one.base(), "value": None, "at": None}
            if one.error is None and one.signal_id:
                if live:
                    got = _value(reader, one, "last", window)
                    row.update(value=got["value"], at=got["at"], error=got["error"])
                if one.meta.get("kind") != "text":
                    wanted.append(one.signal_id)
        rows.append(row)
    series: dict[str, dict[str, Any]] = {}
    unique = list(dict.fromkeys(wanted))
    if unique:
        batch = _batch(reader, unique, start, end, step)
        if batch is None:
            failures = {signal: t("PlantCraft could not be reached.") for signal in unique}
            answers: dict[str, dict[str, Any]] = {}
        else:
            answers, failures = batch
        for signal_id in unique:
            if signal_id in failures:
                series[signal_id] = {"t": [], "v": [], "error": failures[signal_id]}
            else:
                answer = answers.get(signal_id) or {}
                series[signal_id] = {"t": answer.get("t") or [], "v": answer.get("v") or []}
    by_slot = {(element, slot): binding for element, slot, binding in bindings(diagram)}
    for row in rows:
        signal_id = row.get("signal")
        if not live and signal_id and signal_id in series and row.get("kind") != "result":
            line = series[signal_id]
            last = next(
                (
                    (stamp, value)
                    for stamp, value in zip(reversed(line["t"]), reversed(line["v"]), strict=False)
                    if _number(value) is not None
                ),
                None,
            )
            row["value"], row["at"] = (last[1], last[0]) if last else (None, None)
            row["error"] = row.get("error") or line.get("error")
        at = _stamp(row.get("at"))
        row["stale"] = bool(
            live
            and row.get("value") is not None
            and at
            and (end - at).total_seconds() > stale_seconds
        )
        row.update(judge(row["slot"], by_slot.get((row["element"], row["slot"]), {}), row))
    return {
        "read_at": reader.clock().isoformat(),
        "range": {"start": start.isoformat(), "end": end.isoformat(), "step": step, "live": live},
        "bindings": rows,
        "series": series,
    }


def asset_signals(reader: Reader, asset_id: str) -> list[dict[str, Any]]:
    """The roles an asset offers for bindings (the editor lists them first)."""

    try:
        asset = reader.asset(asset_id)
    except Unauthorized:
        raise
    except PlantCraftError:
        return []
    return [
        {"role": role, "signal": signal}
        for role, signal in sorted((asset.get("signals") or {}).items())
    ]
