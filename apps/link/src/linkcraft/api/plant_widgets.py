"""The Overview's two widgets about the whole plant (which loops and signals
are bad now, and where):

- ``in-alarm-history``: how many loops and signals were in alarm, and in warning, each day of the
  last 14, from their stored verdicts (``subject_health`` for loops, ``quality_history`` for
  signals): the status each one ended the day with; today is their status now, as Results
  says it. A day without any verdict is an empty column, not a zero.
- ``health-map``: one square per result (an asset of any type, a control loop being one, and a
  signal), coloured by its latest status, grouped by the area of the asset it belongs to (the
  parent asset in PlantCraft's tree, its parent beside it when two areas share a name), each
  square opening its page. Loops are not a group of their own.

Both read each table once per answer, never once per loop. A past day does not change, so it
is read again every six hours (a replay may fill one in). Days are the installation's.
"""

from __future__ import annotations

import time
import weakref
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk import widgets as w
from plantcraft_sdk.utc import utc_iso

from linkcraft.api.routers.results import RANK, scoped_rows
from linkcraft.data.frames import loop_signal_ids
from linkcraft.engine.zones import zone_of
from linkcraft.i18n import t
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND
from linkcraft.loops.suite import SUITE_STATUS
from linkcraft.signals.publish import STATUS as SIGNAL_STATUS

STATUS_WORDS = {"alarm": "Alarm", "warning": "Warning", "unknown": "Unknown", "ok": "OK"}
DAYS = 14
# A past day is read again after this long.
PAST_SECONDS = 6 * 3600.0
NO_AREA = "No area"

# Per runtime: {day start: (read at, day)}.
_PAST: weakref.WeakKeyDictionary[Any, dict[str, tuple[float, Any]]] = weakref.WeakKeyDictionary()


def day_bounds(now: datetime | None = None, days: int = DAYS) -> list[datetime]:
    """The starts of the last ``days`` days on the installation's clock, and of tomorrow."""

    zone = zone_of(None)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    return [
        datetime.combine(today - timedelta(days=days - 1 - index), datetime.min.time(), zone)
        for index in range(days + 1)
    ]


def _read_day(rt: Any, start: str, end: str) -> tuple[bool, dict[tuple[str, str], str]]:
    """Whether the day has any verdict, and each loop or signal it ended in alarm or warning."""

    loops = rt.latest.statuses_between(APPLICATION_ID, SUBJECT_KIND, start, end)
    signals = rt.quality_results.statuses_between(start, end)
    flagged: dict[tuple[str, str], str] = {}
    for kind, found, words in (("loop", loops, SUITE_STATUS), ("signal", signals, SIGNAL_STATUS)):
        for subject, status in found.items():
            state = words.get(str(status))
            if state in {"alarm", "warning"}:
                flagged[(kind, subject)] = state
    return bool(loops or signals), flagged


def _past(rt: Any, bounds: list[datetime]) -> list[tuple[bool, dict[tuple[str, str], str]]]:
    """The days before today, oldest first."""

    stamps = [utc_iso(moment) for moment in bounds]
    past = _PAST.setdefault(rt, {})
    now = time.monotonic()
    kept: dict[str, tuple[float, Any]] = {}
    found = []
    for start, end in zip(stamps[:-2], stamps[1:-1], strict=True):
        cached = past.get(start)
        if cached is None or now - cached[0] > PAST_SECONDS:
            cached = (now, _read_day(rt, start, end))
        kept[start] = cached
        found.append(cached[1])
    _PAST[rt] = kept
    return found


def alarm_history(rt: Any, scope: Any, root: str) -> dict[str, Any]:
    """Loops and signals in alarm and in warning at the end of each of the last 14 days."""

    rows = scoped_rows(rt, scope, ("loop", "signal"))
    seen = {(row["kind"], row["id"]) for row in rows}
    now = (
        any(row["at"] for row in rows),
        {(row["kind"], row["id"]): row["status"] for row in rows},
    )
    bounds = day_bounds()
    buckets = []
    for start, (judged, flagged) in zip(bounds[:-1], [*_past(rt, bounds), now], strict=True):
        counts = [
            sum(1 for key, state in flagged.items() if state == wanted and key in seen)
            for wanted in ("alarm", "warning")
        ]
        buckets.append((start.timestamp() * 1000, counts if judged else [None, None]))
    today = buckets[-1][1][0]
    return w.columns(
        buckets if any(values[0] is not None for _, values in buckets) else [],
        stacks=[w.stack(t("Alarm"), "alarm"), w.stack(t("Warning"), "warning")],
        step="day",
        value=today,
        label=t("in alarm today"),
        state=None if today is None else "alarm" if today else "ok",
        href=f"{root}/results?status=alarm,warning",
        empty=t("No loop or signal judged in the last 14 days."),
    )


def _areas(
    rt: Any,
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """Where each loop, signal and asset is: (the parent's name, the area's name), by loop, by
    signal and by asset id. From PlantCraft's asset tree as last synced; a loop not in it keeps
    the area and unit it was synced with (or given here)."""

    assets = [
        item
        for item in (getattr(rt.quality_engine, "assets", None) or [])
        if isinstance(item, dict)
    ]
    by_id = {str(item.get("id")): item for item in assets if item.get("id")}

    def place(asset_id: str) -> tuple[str, str] | None:
        own = by_id.get(asset_id) or {}
        parent = by_id.get(str(own.get("parent_id") or ""))
        if not parent or str(parent.get("id")) == asset_id:
            return None
        grand = by_id.get(str(parent.get("parent_id") or "")) or {}
        if str(grand.get("id")) in {asset_id, str(parent.get("id"))}:
            grand = {}
        return (str(grand.get("name") or ""), str(parent.get("name") or parent.get("id")))

    loops: dict[str, tuple[str, str]] = {}
    for row in rt.monitor.overview_rows():
        found = place(str(row["loop_id"]))
        if found is None and row.get("area") and row["area"] != NO_AREA:
            found = (str(row.get("unit") or ""), str(row["area"]))
        if found is not None:
            loops[str(row["loop_id"])] = found
    signals: dict[str, tuple[str, str]] = {}
    # A loop's signals are where the loop is, its SP and mode too, which no asset holds.
    for loop in rt.loops.list_loops():
        if str(loop.loop_id) in loops:
            for signal in loop_signal_ids(loop):
                signals.setdefault(signal, loops[str(loop.loop_id)])
    places: dict[str, tuple[str, str]] = {}
    for asset_id, item in by_id.items():
        where = loops.get(asset_id) or place(asset_id)
        if where is None:
            continue
        places[asset_id] = where
        for signal in (item.get("signals") or {}).values():
            if signal:
                signals.setdefault(str(signal), where)
    return loops, signals, places


def _where(
    row: dict[str, Any], areas: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
) -> tuple[str, str]:
    loops, signals, places = areas
    if row["kind"] == "loop":
        return loops.get(row["id"]) or ("", "")
    if row["kind"] == "signal":
        # A loop may name its signals by tag, without the source (``<source>:<tag>``).
        tag = str(row["id"]).split(":", 1)[-1]
        return signals.get(row["id"]) or signals.get(tag) or ("", "")
    # An algorithm's result on an asset: its id is "<algorithm>:<asset>", the asset its caption.
    return places.get(str(row["caption"])) or loops.get(str(row["caption"])) or ("", "")


def _detail(row: dict[str, Any]) -> str:
    said = row["finding"] or t(STATUS_WORDS.get(row["status"], "Unknown"))
    # An asset can have a result from several algorithms: the square says which one.
    algorithm = (row.get("algorithm") or {}).get("name") if row["kind"] == "asset" else None
    return f"{algorithm}: {said}" if algorithm else said


def health_map(rt: Any, scope: Any, root: str) -> dict[str, Any]:
    """Every result as a square, by area; past ``MAX_TILES`` the ones in alarm and in warning
    are kept first, then the assets, and the card says how many are left out."""

    rows = scoped_rows(rt, scope)
    order = sorted(
        rows,
        key=lambda row: (
            row["status"] not in {"alarm", "warning"},
            row["kind"] == "signal",
            RANK.get(row["status"], 9),
            str(row["name"]).lower(),
        ),
    )
    kept, more = order[: w.MAX_TILES], max(0, len(order) - w.MAX_TILES)
    areas = _areas(rt)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in kept:
        groups.setdefault(_where(row, areas), []).append(row)
    names = [area for _, area in groups if area]
    shared = {area for area in names if names.count(area) > 1}

    def label(where: tuple[str, str]) -> str | None:
        parent, area = where
        if not area:
            return t(NO_AREA) if len(groups) > 1 else None
        return f"{parent} · {area}" if area in shared and parent else area

    ordered = sorted(groups, key=lambda where: (not where[1], (label(where) or "").casefold()))
    data = w.tiles(
        [
            w.group(
                label(where),
                [
                    w.tile(
                        row["name"],
                        row["status"],
                        detail=_detail(row),
                        href=f"{root}{row['path']}",
                    )
                    for row in sorted(
                        groups[where],
                        key=lambda row: (RANK.get(row["status"], 9), str(row["name"]).lower()),
                    )
                ],
            )
            for where in ordered
        ],
        value=len(rows),
        label=t("assets and signals"),
        href=f"{root}/results",
        empty=t("Nothing judged yet."),
    )
    if more:  # left out above, before the squares were grouped
        data["more"] = more
    return data
