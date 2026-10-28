"""What the Historian has open now, for PlantCraft to write as its events.

The Historian answers the suite and never calls it (no app key), so it cannot post events. It
names its open conditions in ``GET /api/ops/metrics`` instead (``plantcraft_sdk.server.ops.
report_conditions``); PlantCraft's monitor reads them every minute and writes a ``start`` when one
appears and an ``end`` when it is gone, as ``histcraft.*`` events Alarms judges (``app.toml``,
``[[publishes.events]]``). Read from what the collector already stores (its heartbeat, each
source's state, each point's snapshot), so it costs no read of the archive:

- ``collector.stalled``: the collector wrote no heartbeat for two minutes (it ran before). While
  it is stalled nothing else is said: the sources' and points' states are its own, old.
- ``source.disconnected``: a live source the collector cannot read (key ``source:<id>``).
- ``point.no_data``: an archived point of a connected source whose last value is bad or older
  than ten of its scans (at least ten minutes; key ``point:<id>``). Points of a disconnected
  source are its source's condition, not one each. Each point is one condition, said once
  when it starts and once when it ends (never again while it lasts); points the collector does
  not read (written by an app or PlantCraft, imported) are never named; at most ``MAX_POINTS``
  (what the SDK lets an app report, less room for the others) are named, the oldest first.
- ``archive.disk_low``: the disk forecast the collector's housekeeping stores hourly
  (``archive.forecast``) fills the disk in fewer than ``ALERT_DAYS`` days (key ``disk``).
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.events import MAX_CONDITIONS, Condition

from histcraft.archive.forecast import ALERT_DAYS
from histcraft.archive.store import now_ms
from histcraft.catalog.models import IMPORT_KIND, LIVE_KINDS, WRITTEN_KINDS
from histcraft.i18n import t

HEARTBEAT_MS = 120_000
STALE_SCANS = 10
STALE_MIN_MS = 600_000
MAX_POINTS = MAX_CONDITIONS - 10
ARCHIVED = ("archive", "both")
# Sources the collector does not read: what an app or PlantCraft writes, and imported files. A
# gap there is their writer's business (an algorithm's version is written once per version).
UNCOLLECTED = (*WRITTEN_KINDS, IMPORT_KIND)


def open_conditions(catalog: Any, archive: Any, *, now: int | None = None) -> list[Condition]:
    """The conditions open now (``catalog``: ``CatalogStore``; ``archive``: ``ArchiveStore``)."""

    now = now_ms() if now is None else now
    state = archive.state()
    collector = state.get("collector") or {}
    heartbeat = collector.get("heartbeat")
    if not heartbeat:
        return []  # no collector ever ran here (the collector is off): nothing to say
    if now - int(heartbeat) > HEARTBEAT_MS:
        minutes = round((now - int(heartbeat)) / 60_000)
        return [
            Condition(
                name="collector.stalled",
                key="collector",
                summary=t("The collector wrote nothing for {minutes} min", minutes=minutes),
                payload={"heartbeat_ms": int(heartbeat)},
            )
        ]
    found: list[Condition] = []
    status = collector.get("sources") or {}
    down: set[str] = set()
    for source in catalog.sources():
        if source.get("kind") not in LIVE_KINDS or not source.get("enabled", True):
            continue
        current = status.get(source["id"]) or {}
        if current.get("status") != "disconnected":
            continue
        down.add(source["id"])
        detail = str(current.get("detail") or "")
        found.append(
            Condition(
                name="source.disconnected",
                key=f"source:{source['id']}",
                subject=f"source:{source['id']}",
                summary=t(
                    "Source {name} disconnected: {detail}",
                    name=source.get("name") or source["id"],
                    detail=detail or "?",
                )[:500],
                payload={
                    "source": source["id"],
                    "detail": detail[:300],
                    "since_ms": current.get("since"),
                },
            )  # fmt: skip
        )
    skipped = down | {
        source["id"] for source in catalog.sources() if source.get("kind") in UNCOLLECTED
    }
    found += _points(catalog, archive, skipped, now)
    found += _disk(state.get("forecast") or {})
    return found


def _disk(forecast: dict[str, Any]) -> list[Condition]:
    days = forecast.get("days_to_full")
    if days is None or float(days) >= ALERT_DAYS:
        return []
    return [
        Condition(
            name="archive.disk_low",
            key="disk",
            summary=t("The disk fills in {days} days at the archive's growth", days=round(days)),
            payload={
                "days_to_full": float(days),
                "free_bytes": forecast.get("free_bytes"),
                "bytes_per_day": forecast.get("bytes_per_day"),
            },
        )
    ]


def stale_ms(point: dict[str, Any]) -> int:
    """How long a collected point may go without a value: ten of its scans, at least ten
    minutes."""

    scan_ms = max(float(point.get("scan_seconds") or 1.0), 0.1) * 1000
    return max(STALE_MIN_MS, int(STALE_SCANS * scan_ms))


def _points(catalog: Any, archive: Any, down: set[str], now: int) -> list[Condition]:
    points = [
        point
        for point in catalog.points(enabled_only=True, modes=ARCHIVED)
        if point.get("source_id") not in down
    ]
    snaps = archive.snapshots([int(point["id"]) for point in points])
    late: list[tuple[int, dict[str, Any], str]] = []
    for point in points:
        snap = snaps.get(int(point["id"]))
        if snap is None:
            continue  # never read yet: waiting, not lost
        age = now - int(snap.get("ts") or snap.get("updated") or now)
        if snap.get("status") == "bad":
            late.append((age, point, str(snap.get("detail") or t("bad value"))))
        elif snap.get("status") in ("ok", "uncertain", "substituted") and age > stale_ms(point):
            late.append((age, point, t("no value for {minutes} min", minutes=round(age / 60_000))))
    late.sort(key=lambda item: -item[0])
    found = []
    for _, point, detail in late[:MAX_POINTS]:
        tag = str(point.get("tag") or point["id"])
        found.append(
            Condition(
                name="point.no_data",
                key=f"point:{point['id']}",
                subject=f"signal:{point['source_id']}:{tag}",
                summary=f"{tag}: {detail}"[:500],
                payload={"point": int(point["id"]), "source": point.get("source_id")},
            )
        )
    return found
