"""What a chart in the assistant's answer draws: the window, the signals and their statistics."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from plantcraft.assistant_chat.engine_common import Reader


def _when(value: Any, default: datetime) -> datetime:
    if not value:
        return default
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{value} is not an ISO 8601 time") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_local(moment: datetime) -> str:
    """A time on its own clock with its offset: ``2026-11-03T11:18-03:00``."""

    return moment.isoformat(timespec="minutes")


def _stats(values: list[Any]) -> dict[str, Any]:
    numbers = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    ]
    if not numbers:
        return {"points": len(values), "numeric": 0}
    return {
        "points": len(values),
        "first": numbers[0],
        "last": numbers[-1],
        "min": min(numbers),
        "max": max(numbers),
        "mean": round(sum(numbers) / len(numbers), 6),
    }


def signal_of(reader: Reader, signal_id: str) -> dict[str, Any]:
    """A signal as the person reads it (``GET /api/v1/signals/{id}``); empty when it cannot be
    read."""

    if not signal_id:
        return {}
    status, signal = reader("GET", f"/api/v1/signals/{quote(signal_id, safe='')}", {})
    return signal if status < 400 and isinstance(signal, dict) else {}


def unit_of(reader: Reader, signal_id: str) -> str:
    """A signal's unit, read as the person (empty when it has none or cannot be read)."""

    return str(signal_of(reader, signal_id).get("unit") or "")


def signal_label(signal_id: str, signal: dict[str, Any]) -> str:
    """How a chart names a signal: its tag without the source and the folders before it
    (``plantcraft:CPM.Loops.FIC-1003.PV`` is ``FIC-1003.PV``), then its description or a name
    that says more than the tag."""

    tag = signal_id.split(":", 1)[1] if ":" in signal_id else signal_id
    parts = tag.split(".")
    short = ".".join(parts[-2:]) if len(parts) > 2 else tag
    name = str(signal.get("name") or "").strip()
    about = str(signal.get("description") or "").strip()
    if not about and name and name not in (short, tag, parts[-1], signal_id):
        about = name
    return f"{short} · {about}"[:120] if about and about != short else short
