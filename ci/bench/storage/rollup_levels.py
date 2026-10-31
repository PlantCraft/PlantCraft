"""Daily and monthly rollups (H9): a year's read and disk before and after, on PostgreSQL.

    HISTCRAFT_BENCH_DATABASE_URL=postgresql://... python ci/bench/storage/rollup_levels.py

Writes a year of ``POINTS`` signals at ``RATE`` archived values a day (940: the demo plant's
rate after compression) as the collector leaves them (a chunk per signal and day), builds the
hourly rollups only ("before", Historian 0.5), then the daily and monthly ones ("after"), and
times one signal's year as a daily trend and as a 365-day mean, cold and warm. Then it keeps the
raw values 90 days and the rollups a year, and reads the year again. Prints one JSON line;
``rollup_levels.md`` has the numbers.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "historian" / "src"))

from histcraft.archive import rollup  # noqa: E402
from histcraft.archive.query import PointRef, Reader, to_ms  # noqa: E402
from histcraft.archive.store import ArchiveStore  # noqa: E402
from histcraft.db import Database  # noqa: E402

URL = os.environ["HISTCRAFT_BENCH_DATABASE_URL"]
POINTS = int(os.environ.get("POINTS", 50))
RATE = int(os.environ.get("RATE", 940))
DAYS = 365
DAY = 86_400_000
END = datetime(2026, 10, 1, tzinfo=timezone.utc)
START = END - timedelta(days=DAYS)


def seed(archive: ArchiveStore) -> int:
    rng = np.random.default_rng(3)
    start = to_ms(START)
    every = DAY // RATE
    written = 0
    for day in range(DAYS):
        batch = {}
        for point in range(1, POINTS + 1):
            times = start + day * DAY + np.arange(RATE, dtype=np.int64) * every
            values = 50 + np.cumsum(rng.normal(0, 0.05, RATE)) + 10 * np.sin(times / 8.64e7)
            batch[point] = ("number", list(zip(times.tolist(), values.tolist(), strict=True)))
        written += archive.append(batch)
    return written


def size(archive: ArchiveStore) -> dict[str, int]:
    with archive._connect() as connection:  # noqa: SLF001 - a bench reads the tables' sizes

        def total(pattern: str) -> int:
            row = connection.execute(
                "SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) AS b FROM pg_class c"
                " WHERE c.relkind = 'r' AND c.relname LIKE ?",
                (pattern,),
            ).fetchone()
            return int(row["b"])

        return {
            "chunks": total("chunks%"),
            "hourly": total("rollups\\_y%") + total("rollups\\_edge%"),
            "coarse": total("rollups_coarse"),
        }


def timed(read, repeat: int = 7) -> dict[str, float]:
    cold_start = time.perf_counter()
    read()
    cold = time.perf_counter() - cold_start
    warm = []
    for _ in range(repeat):
        begin = time.perf_counter()
        read()
        warm.append(time.perf_counter() - begin)
    return {"first_ms": round(cold * 1000, 1), "warm_ms": round(statistics.median(warm) * 1000, 1)}


def reads(archive: ArchiveStore, point: PointRef) -> dict[str, object]:
    reader = Reader(archive)
    trend = timed(lambda: reader.series(point, START, END, 86_400))
    window = timed(lambda: reader.value(point, "mean", "364d", now=END - timedelta(hours=2)))
    _, values = reader.series(point, START, END, 86_400)
    mean = reader.value(point, "mean", "364d", now=END - timedelta(hours=2))["value"]
    return {
        "daily_trend": trend,
        "mean_364d": window,
        "days_with_value": sum(v is not None for v in values),
        "mean": mean,
    }


def main() -> None:
    db = Database(URL)
    archive = ArchiveStore(db)
    began = time.perf_counter()
    values = seed(archive)
    seeded = time.perf_counter() - began
    points = [(point, False) for point in range(1, POINTS + 1)]
    probe = PointRef(1, "bench:P1")
    # Before: Historian 0.5, hourly rollups only.
    original = rollup.build_coarse
    rollup.build_coarse = lambda *args, **kwargs: (0, 0)
    rollup.build(archive, points, hours=DAYS * 24)
    rollup.build_coarse = original
    before = {"reads": reads(archive, probe), "disk": size(archive), "rows": archive.rollup_rows()}
    print(json.dumps({"before": before}), file=sys.stderr)
    # After: the daily and monthly rollups.
    began = time.perf_counter()
    for point, step in points:
        rollup.build_coarse(archive, point, step, to_ms(END))
    coarse_s = time.perf_counter() - began
    after = {"reads": reads(archive, probe), "disk": size(archive), "rows": archive.rollup_rows()}
    # Raw values kept 90 days, hourly rollups a year, days and months forever.
    now = to_ms(END)
    archive.prune(
        {point: now - 90 * DAY for point, _ in points},
        {"hour": {point: now - 365 * DAY for point, _ in points}, "day": {}, "month": {}},
    )
    import psycopg

    with psycopg.connect(URL, autocommit=True) as connection:
        connection.execute("VACUUM FULL")
    kept = {"reads": reads(archive, probe), "disk": size(archive), "rows": archive.rollup_rows()}
    print(
        json.dumps(
            {
                "points": POINTS,
                "values": values,
                "seed_s": round(seeded, 1),
                "coarse_build_s": round(coarse_s, 2),
                "before": before,
                "after": after,
                "raw_90_days": kept,
                "bytes_per_row": {
                    "hour": round(after["disk"]["hourly"] / max(1, after["rows"]["hour"]), 1),
                    "coarse": round(
                        after["disk"]["coarse"]
                        / max(1, after["rows"]["day"] + after["rows"]["month"]),
                        1,
                    ),
                },
            }
        )
    )


if __name__ == "__main__":
    main()
