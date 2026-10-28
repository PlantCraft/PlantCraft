"""The Historian's widgets: declared in ``app.toml`` (``[[contributes.widgets]]``), drawn on the
Historian's Overview and on Desk's Today alike (PlantCraft ``docs/widgets.md``). They say how
the points are collected (by status, and as a map of every signal by source), what the archive
holds and stores per hour, and how one point moved in the last hour. Links are paths on this
host, under the Historian's prefix.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk import widgets as w
from plantcraft_sdk.asset_scope import EVERYTHING, AssetScope

from histcraft.api.deps import CurrentUser, RuntimeDep, Scope
from histcraft.api.routers.admin import overview
from histcraft.api.runtime import point_ref
from histcraft.archive.query import SourceUnavailable
from histcraft.catalog.models import CatalogError
from histcraft.clock import now_ms
from histcraft.conditions import UNCOLLECTED, stale_ms
from histcraft.i18n import t
from histcraft.meta import FILES

router = APIRouter(prefix="/api")

PROBLEMS = ("bad", "disconnected", "waiting")
# A collection status, in words and as the suite's colour.
STATUS = {
    "ok": ("Collecting", "ok"),
    "uncertain": ("Uncertain value", "warning"),
    "substituted": ("Substituted value", "warning"),
    "bad": ("Bad value", "alarm"),
    "disconnected": ("Disconnected", "alarm"),
    "waiting": ("Waiting", "unknown"),
    "disabled": ("Disabled", "off"),
    "imported": ("Imported", "ok"),
    "written": ("Written by its app", "ok"),
}
# A point that is fine but not collected by Historian: its words by its source's kind.
OK_AS = {"import": "imported", "derived": "written", "system": "written"}
TREND_MINUTES = 60
TREND_STEP_S = 60.0
# Past this many years a disk forecast is no forecast: "Not in sight" (not 623046 days).
YEARS_IN_SIGHT = 10
STORED_HOURS = 24
HOUR_MS = 3_600_000
# A signal's square on the source map: collecting, late or uncertain, not collecting.
TILE_STATE = {
    "uncertain": "warning",
    "substituted": "warning",
    "bad": "alarm",
    "disconnected": "alarm",
    "waiting": "alarm",
}
WORST = ("alarm", "warning", "ok", "unknown")


def _statuses(runtime: Any, scope: AssetScope = EVERYTHING) -> list[tuple[dict[str, Any], str]]:
    snaps = runtime.archive.snapshots()
    return [
        (point, (snaps.get(point["id"]) or {}).get("status", "waiting"))
        for point in runtime.catalog.points()
        if point["enabled"] and scope.signal(point["signal"])
    ]


def _bytes(count: float | None) -> str:
    if count is None:
        return "—"
    size = float(count)
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1000:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{size:.1f} TB"


def _numbers(runtime: Any, scope: AssetScope = EVERYTHING) -> list[dict[str, Any]]:
    return [
        point
        for point in runtime.catalog.points()
        if point["enabled"]
        and point.get("kind", "number") == "number"
        and scope.signal(point["signal"])
    ]


def _source_line(found: dict[str, Any], live: dict[str, Any] | None) -> str | None:
    """A source's kind and since when it is connected or not, said as such ("OPC UA ·
    Connected 5 h ago"), never a bare time."""

    kind = str(found.get("kind") or "").upper() or None
    when = w.ago((live or {}).get("since"), t)
    status = None
    if live and when:
        status = (
            t("Connected {when}", when=when)
            if live.get("status") == "connected"
            else t("Disconnected {when}", when=when)
        )
    return " · ".join(part for part in (kind, status) if part) or None


@router.get("/widgets")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(FILES.manifest(), t)


@router.get("/widgets/{widget_id}/options")
def widget_options(widget_id: str, runtime: RuntimeDep, scope: Scope) -> dict[str, Any]:
    if widget_id != "trend":
        raise HTTPException(status_code=404, detail=t("Widget not found."))
    return w.options(
        w.option(point["signal"], point["tag"], point.get("name") or point.get("source_id"))
        for point in _numbers(runtime, scope)
    )


@router.get("/widgets/{widget_id}")
def widget(
    widget_id: str,
    runtime: RuntimeDep,
    user: CurrentUser,
    scope: Scope,
    item: str | None = Query(default=None, max_length=400),
) -> dict[str, Any]:
    root = runtime.settings.root_path
    if widget_id in {"points", "not-collecting", "statuses"}:
        return _points(runtime, root, widget_id, scope)
    if widget_id == "trend":
        return _trend(runtime, root, item, scope)
    if widget_id == "stored":
        return _stored(runtime, root, scope)
    if widget_id == "source-map":
        return _source_map(runtime, root, scope)
    state = overview(runtime, user)
    collector, archive = state["collector"], state["archive"]
    if widget_id == "collector":
        sources = collector["sources"]
        connected = sum(1 for entry in sources.values() if entry.get("status") == "connected")
        since = [
            t("Started {ago}", ago=w.ago(collector.get("started"), t))
            if collector.get("started")
            else None,
            t("last seen {ago}", ago=w.ago(collector.get("heartbeat"), t))
            if collector.get("heartbeat")
            else None,
        ]
        # A list like every other card: whether it runs and how fast, then the sources it reaches.
        return w.items(
            [
                w.item(
                    t("Running") if collector["running"] else t("Stopped"),
                    detail=" · ".join(part for part in since if part) or None,
                    value=t("{rate} values/s", rate=f"{collector['reads_per_second']:g}"),
                    state="ok" if collector["running"] else "alarm",
                    href=f"{root}/sources",
                ),
                w.item(
                    t("Sources connected"),
                    detail=", ".join(sorted(sources)) or None,
                    value=f"{connected} / {len(sources)}",
                    state="ok"
                    if sources and connected == len(sources)
                    else "warning"
                    if sources
                    else None,
                    href=f"{root}/sources",
                ),
            ],
            href=f"{root}/sources",
        )
    if widget_id == "archive":
        future = archive.get("forecast") or {}
        days = future.get("days_to_full")
        alert = future.get("alert_days") or 30
        oldest = w.ago(archive.get("oldest"), t)
        # Whether the disk holds; bytes per value and compression stay on the Settings page.
        return w.items(
            [
                w.item(
                    t("On disk"),
                    detail=t("Grows {bytes} a day", bytes=_bytes(future.get("bytes_per_day"))),
                    value=_bytes(archive.get("file_bytes")),
                    href=f"{root}/settings",
                ),
                w.item(
                    t("Disk full in"),
                    detail=t("{bytes} free", bytes=_bytes(future.get("free_bytes"))),
                    value=t("{days} days", days=f"{days:g}")
                    if isinstance(days, int | float) and days <= YEARS_IN_SIGHT * 365
                    else t("Not in sight"),
                    state="warning" if isinstance(days, int | float) and days < alert else "ok",
                    href=f"{root}/settings",
                ),
                w.item(
                    t("Values archived"),
                    detail=t("Oldest value {ago}", ago=oldest) if oldest else None,
                    value=f"{archive['values']:,}",
                    href=f"{root}/settings",
                ),
            ],
            href=f"{root}/settings",
        )
    if widget_id == "sources":
        sources = {item["id"]: item for item in runtime.catalog.sources()}
        live = collector["sources"]
        return w.items(
            [
                w.item(
                    source_id,
                    detail=_source_line(found, live.get(source_id)),
                    state="ok"
                    if (live.get(source_id) or {}).get("status") == "connected"
                    else "alarm"
                    if source_id in live
                    else "unknown",
                    href=f"{root}/sources",
                )
                for source_id, found in sources.items()
            ],
            href=f"{root}/sources",
            empty=t("Add the OPC UA server to read from, then pick its variables."),
        )
    raise HTTPException(status_code=404, detail=t("Widget not found."))


def _points(runtime: Any, root: str, widget_id: str, scope: AssetScope) -> dict[str, Any]:
    rows = _statuses(runtime, scope)
    problems = [(point, status) for point, status in rows if status in PROBLEMS]
    if widget_id == "points":
        collecting = len(rows) - len(problems)
        return w.number(
            collecting,
            label=t(
                "of {total} enabled; {count} not collecting", total=len(rows), count=len(problems)
            )
            if problems
            else t("of {total} enabled, all collecting", total=len(rows)),
            state="warning" if problems else "ok",
            href=f"{root}/points",
        )
    if widget_id == "statuses":
        counts: dict[str, int] = {}
        for point, status in rows:
            # A fine imported or app-written point is not "collecting" (as the Points page says).
            if status == "ok" and point.get("source_kind") in OK_AS:
                status = OK_AS[point["source_kind"]]
            counts[status] = counts.get(status, 0) + 1
        disabled = sum(
            1
            for point in runtime.catalog.points()
            if not point["enabled"] and scope.signal(point["signal"])
        )
        if disabled:
            counts["disabled"] = disabled
        return w.split(
            [
                w.part(t(STATUS[status][0]), counts[status], STATUS[status][1], f"{root}/points")
                for status in STATUS
                if counts.get(status)
            ],
            label=t("signals"),
            href=f"{root}/points",
            empty=t("No signal yet."),
        )
    return w.items(
        [
            w.item(
                point["tag"],
                detail=point.get("source_id") or "",
                value=t(STATUS[status][0]),
                state={"bad": "alarm", "disconnected": "alarm", "waiting": "warning"}[status],
                href=f"{root}/points",
            )
            for point, status in problems[:8]
        ],
        href=f"{root}/points",
        empty=t("Every enabled signal is collecting."),
    )


def _trend(runtime: Any, root: str, signal: str | None, scope: AssetScope) -> dict[str, Any]:
    """One point over the last hour, a minute per value; without a choice, the first number
    (of those in the caller's part of the plant)."""

    numbers = _numbers(runtime, scope)
    point = next((entry for entry in numbers if entry["signal"] == signal), None)
    point = point or (numbers[0] if numbers else None)
    if point is None:
        return w.series([], empty=t("No signal yet."))
    end = datetime.now(UTC)
    start = end - timedelta(minutes=TREND_MINUTES)
    href = f"{root}/points/{quote(point['signal'], safe='')}"
    try:
        stamps, values = runtime.reader.series(point_ref(point), start, end, TREND_STEP_S)
    except (CatalogError, SourceUnavailable, ValueError) as exc:
        return w.series([], label=point["tag"], empty=str(exc), href=href)
    points = []
    for stamp, value in zip(stamps, values, strict=False):
        at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp() * 1000
        number = float(value) if isinstance(value, int | float) else None
        points.append((at, number if number is None or math.isfinite(number) else None))
    last = next((value for _, value in reversed(points) if value is not None), None)
    return w.series(
        points,
        value=None if last is None else round(last, 3),
        unit=point.get("unit") or None,
        label=t("{tag}, last hour", tag=point["tag"]),
        href=href,
        empty=t("No value in the last hour."),
    )


def _stored(runtime: Any, root: str, scope: AssetScope) -> dict[str, Any]:
    """Values stored per hour of their time over the last 24 h, from the per-hour counts the
    archive keeps as it writes (``point_hours``): never a read of the values themselves."""

    end = now_ms()
    first = end - end % HOUR_MS - (STORED_HOURS - 1) * HOUR_MS
    ids = None
    if not scope.everything:
        ids = [
            int(point["id"]) for point in runtime.catalog.points() if scope.signal(point["signal"])
        ]
    counts = runtime.archive.hour_counts(first, ids) if ids is None or ids else {}
    hours = [first + index * HOUR_MS for index in range(STORED_HOURS)]
    return w.columns(
        [(hour, counts.get(hour, 0)) for hour in hours],
        step="hour",
        value=sum(counts.get(hour, 0) for hour in hours),
        label=t("values stored in 24 h"),
        href=f"{root}/settings",
        empty=t("No value stored in the last 24 h."),
    )


def _tile(point: dict[str, Any], snap: dict[str, Any] | None, now: int) -> tuple[str, str]:
    """A signal's square: its state and the words beside its tag."""

    if not point.get("source_enabled", True):
        return "unknown", t("Source disabled")
    snap = snap or {}
    status = snap.get("status", "waiting")
    if status in TILE_STATE:
        return TILE_STATE[status], t(STATUS[status][0])
    kind = point.get("source_kind")
    if kind in OK_AS:
        return "ok", t(STATUS[OK_AS[kind]][0])
    age = now - int(snap.get("ts") or snap.get("updated") or now)
    if kind not in UNCOLLECTED and age > stale_ms(point):
        return "warning", t("No value for {minutes} min", minutes=round(age / 60_000))
    return "ok", t(STATUS["ok"][0])


def _source_map(runtime: Any, root: str, scope: AssetScope) -> dict[str, Any]:
    """Every enabled signal as a square, grouped by its source, coloured by how its collection
    goes: collecting, late or uncertain, not collecting, its source disabled."""

    snaps = runtime.archive.snapshots()
    now = now_ms()
    groups: dict[str, list[dict[str, Any]]] = {}
    kinds: dict[str, str] = {}
    for point in runtime.catalog.points():
        if not point["enabled"] or not scope.signal(point["signal"]):
            continue
        state, detail = _tile(point, snaps.get(point["id"]), now)
        kinds[str(point.get("source_id") or "")] = str(point.get("source_kind") or "")
        # What the signal is beside how it goes: the square's hover says both.
        about = point.get("description") or point.get("name")
        groups.setdefault(str(point.get("source_id") or ""), []).append(
            w.tile(
                point["tag"],
                state,
                detail=f"{detail} · {about}" if about and about != point["tag"] else detail,
                href=f"{root}/points/{quote(point['signal'], safe='')}",
            )
        )
    # The sources with a signal not collecting first, then the plant's own, the series apps and
    # PlantCraft write last (they are fine by being written), disabled ones at the very end: a
    # card too small for every square scrolls, and what needs a look stays in sight.
    order = sorted(
        groups,
        key=lambda source: (
            min(WORST.index(tile["state"]) for tile in groups[source]),
            kinds.get(source) in OK_AS,
            source,
        ),
    )
    return w.tiles(
        [
            w.group(source, groups[source], href=f"{root}/sources/{quote(source, safe='')}")
            for source in order
        ],
        value=sum(len(squares) for squares in groups.values()),
        label=t("signals enabled"),
        href=f"{root}/points",
        empty=t("No signal enabled yet."),
    )
