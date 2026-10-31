"""The bench plant's past in Historian; run inside its container by ci/bench/age.py.

    docker compose exec -T -e DAYS=91 histcraft python - < hist_age.py      # age to 91 days
    docker compose exec -T -e MEASURE=1 histcraft python - < hist_age.py    # housekeeping only

Writes the ``bench`` signals' history (``suite_bench.py --keep`` made them) from ``DAYS`` ago up to
their oldest value, so a test installation looks months old. The values are what the collector
keeps after compression, ``RATE`` per signal per day (940 by default: the Mac mini's demo plant,
37.4 million values for 4,800 signals over 8.3 days; a setpoint only ``SP_RATE``), as a random
walk. They go in as the collector's housekeeping leaves them: one chunk per signal per simulated
hour, merged at the end of each simulated day (``compact``), every month rewritten once closed
(``rewrite_closed``) and the hourly rollups of long trends built (``rollup.build``). Running it
again with a larger ``DAYS`` adds only the older days. Prints one JSON line.

``MEASURE=1`` writes nothing: it times one pass of the collector's hourly housekeeping (retention,
compaction, month rewrite, rollups) on the archive as it is, and gives the archive's size.
"""

import json
import os
import time
from datetime import datetime, timezone

import numpy as np
from histcraft.archive import rollup
from histcraft.archive.store import ArchiveStore
from histcraft.catalog.store import CatalogStore
from histcraft.config import Settings
from histcraft.db import Database

SOURCE = "bench"
DAYS = float(os.environ.get("DAYS", 91))
RATE = float(os.environ.get("RATE", 940))
SP_RATE = float(os.environ.get("SP_RATE", 24))
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS

settings = Settings.from_environment()
password = settings.database_password()
catalog = CatalogStore(Database(settings.config_target, password=password))
archive = ArchiveStore(Database(settings.archive_target, password=password))


def now_ms() -> int:
    return int(time.time() * 1000)


def sizes() -> dict:
    out = {"archive_bytes": archive.file_bytes()}
    if archive.db.postgres:
        with archive.db.connect() as connection:
            out["chunks"] = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
            out["rollups"] = int(connection.execute("SELECT COUNT(*) FROM rollups").fetchone()[0])
    return out


def housekeeping() -> dict:
    """One pass of ``collector.service.housekeeping`` (without the catalog's purge), timed."""

    current = now_ms()
    points = catalog.points()
    timed = {}
    began = time.perf_counter()
    cutoffs = {
        int(p["id"]): current - int(p["retention_days"]) * DAY_MS
        for p in points
        if int(p["retention_days"] or 0) > 0
    }
    archive.prune(cutoffs)
    timed["prune_s"] = round(time.perf_counter() - began, 2)
    began = time.perf_counter()
    archive.compact(current - HOUR_MS)
    timed["compact_s"] = round(time.perf_counter() - began, 2)
    began = time.perf_counter()
    archive.rewrite_closed(current)
    timed["rewrite_s"] = round(time.perf_counter() - began, 2)
    began = time.perf_counter()
    rollup.build(
        archive, [(int(p["id"]), bool(p["step"])) for p in points if p["kind"] == "number"]
    )
    timed["rollups_s"] = round(time.perf_counter() - began, 2)
    timed["total_s"] = round(sum(timed.values()), 2)
    return timed


def write_hour(ids: list[int], start: int, counts: np.ndarray, level: np.ndarray, rng) -> int:
    """One chunk per point for the hour from ``start``, as ``ArchiveStore.append`` stores it."""

    runs = {}
    for index, point in enumerate(ids):
        count = int(counts[index])
        if count == 0:
            continue
        times = np.sort(rng.integers(start, start + HOUR_MS, count, dtype=np.int64))
        times = np.unique(times)
        steps = rng.normal(0, 0.15, len(times)).cumsum()
        values = np.clip(level[index] + steps, 0.0, 100.0)
        level[index] = values[-1]
        runs[point] = ("number", times, values)

    def write():
        with archive._lock, archive._connect() as connection:
            return archive._append_runs(connection, runs)

    return archive._writing(write)


def age() -> dict:
    points = catalog.points(source_id=SOURCE)
    if not points:
        raise SystemExit("no bench signals: run suite_bench.py --scale target --keep first")
    ids = [int(p["id"]) for p in points]
    rates = np.array([SP_RATE if p["tag"].endswith(".SP") else RATE for p in points]) / 24
    spans = [archive.span(point) for point in ids[:: max(1, len(ids) // 50)]]
    oldest = min(span[0] for span in spans if span) if any(spans) else now_ms()
    end = oldest // HOUR_MS * HOUR_MS
    start = (now_ms() - int(DAYS * DAY_MS)) // DAY_MS * DAY_MS
    result = {"points": len(ids), "days": DAYS, "rate_per_day": RATE, "written": 0}
    if start >= end:
        result.update(already_aged=True, **sizes())
        return result
    rng = np.random.default_rng(start // DAY_MS)
    level = rng.uniform(20, 80, len(ids))
    began = time.perf_counter()
    compact_times, rewrite_times, write_seconds = [], [], 0.0
    # Newest day first, so a run stopped half way leaves the history whole up to where it got and
    # the next run goes on from there. A month is rewritten once its first day is written.
    day_end, done = end, 0
    while day_end > start:
        day_start = max(start, (day_end - 1) // DAY_MS * DAY_MS)
        flushed = time.perf_counter()
        for hour in range(day_end - HOUR_MS, day_start - 1, -HOUR_MS):
            result["written"] += write_hour(ids, hour, rng.poisson(rates), level, rng)
        write_seconds += time.perf_counter() - flushed
        merged = time.perf_counter()
        archive.compact(day_end, ids)
        compact_times.append(time.perf_counter() - merged)
        if datetime.fromtimestamp(day_start / 1000, timezone.utc).day == 1 or day_start == start:
            rewritten = time.perf_counter()
            while archive.rewrite_closed(now_ms()):
                pass
            rewrite_times.append(round(time.perf_counter() - rewritten, 1))
        day_end, done = day_start, done + 1
        print(json.dumps({"days": done, "written": result["written"]}), flush=True)
    rolled = time.perf_counter()
    hours = rollup.build(archive, [(p, False) for p in ids], hours=int(DAYS * 24) + 48)
    result.update(
        seconds=round(time.perf_counter() - began, 1),
        write_seconds=round(write_seconds, 1),
        values_per_second=round(result["written"] / max(write_seconds, 1e-9)),
        compact_per_day_s={
            "first": round(compact_times[0], 2),
            "last": round(compact_times[-1], 2),
            "max": round(max(compact_times), 2),
        },
        month_rewrites_s=rewrite_times,
        rollup_hours=hours,
        rollup_seconds=round(time.perf_counter() - rolled, 1),
        **sizes(),
    )
    return result


if os.environ.get("MEASURE"):
    print(json.dumps({"housekeeping": housekeeping(), **sizes()}))
else:
    print(json.dumps(age()))
