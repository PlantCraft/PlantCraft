"""Benchmark: can one collector keep up with a plant, and how fast are reads?

``python -m histcraft.bench --points 2000 --seconds 3600`` feeds ``points``
synthetic signals (random walks with noise, one value per second) through the
compressors and writes them as the collector does (one flush every 5 s, one row of recent
values; every minute they move into chunks: ``ArchiveStore.hold``, ``settle``), then reads a
day-long grid back. It reports the values handled per second (a plant of 2,000 points at 1 s
needs 2,000), the compression ratio, the bytes per value on disk and the read times. No OPC UA here: this measures HistCraft, not a
server.

``--database-url postgresql://...`` runs it on PostgreSQL (in a schema of its own, dropped
afterwards; the password from ``PGPASSWORD``) instead of a temporary SQLite file.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import numpy as np

from histcraft.archive.compression import Compressor
from histcraft.archive.query import PointRef, Reader, from_ms
from histcraft.archive.store import ArchiveStore
from histcraft.db import Database, scratch_schema

FLUSH_SECONDS = 5
ARCHIVE_SECONDS = 60


def run(points: int, seconds: int, deviation: float, target: str | Path) -> dict:
    archive = ArchiveStore(Database(target))
    rng = np.random.default_rng(42)
    start_ms = 1_790_000_000_000
    level = rng.uniform(10, 90, points)
    compressors = [Compressor(deviation=deviation, max_seconds=3600) for _ in range(points)]
    pending: list[list] = [[] for _ in range(points)]
    archived = 0
    flushes: list[float] = []
    began = time.perf_counter()
    for second in range(seconds):
        level += rng.normal(0, 0.05, points)
        values = level + rng.normal(0, 0.02, points)
        at = start_ms + second * 1000
        for index in range(points):
            out = compressors[index].feed(at, float(values[index]))
            if out:
                pending[index].extend(out)
        if (second + 1) % FLUSH_SECONDS == 0:
            batch = {i + 1: ("number", p) for i, p in enumerate(pending) if p}
            flushed = time.perf_counter()
            archived += archive.hold(batch)
            if (second + 1) % ARCHIVE_SECONDS == 0:
                archive.settle()
            flushes.append(time.perf_counter() - flushed)
            pending = [[] for _ in range(points)]
    archive.settle()
    collect_seconds = time.perf_counter() - began
    began = time.perf_counter()
    merged = archive.compact(start_ms + seconds * 1000 + 1)
    compact_seconds = time.perf_counter() - began
    stats = archive.point_stats()
    stored_bytes = sum(item["bytes"] for item in stats.values())
    reader = Reader(archive)
    end = from_ms(np.array([start_ms + seconds * 1000]))[0].to_pydatetime()
    begin = end - timedelta(days=1)
    began = time.perf_counter()
    sample = min(points, 100)
    for index in range(sample):
        reader.series(PointRef(index + 1, f"P{index}"), begin, end, 60)
    read_seconds = (time.perf_counter() - began) / sample
    began = time.perf_counter()
    reader.series(PointRef(1, "P0"), begin, end, None)
    raw_seconds = time.perf_counter() - began
    feeds = points * seconds
    return {
        "database": archive.db.dialect,
        "points": points,
        "seconds": seconds,
        "deviation": deviation,
        "values_per_second": round(feeds / collect_seconds),
        "realtime_factor": round(feeds / collect_seconds / points, 1),
        "compression_ratio": round(feeds / max(archived, 1), 1),
        "bytes_per_value_read": round(stored_bytes / feeds, 3),
        "bytes_per_value_archived": round(stored_bytes / max(archived, 1), 2),
        # A flush must cost the same however many chunks wait for compaction (the collector
        # flushes every 5 s and compacts hourly): the first and last minute's mean flush.
        "flush_ms_first_minute": round(1000 * float(np.mean(flushes[:12] or [0])), 1),
        "flush_ms_last_minute": round(1000 * float(np.mean(flushes[-12:] or [0])), 1),
        "compact_seconds": round(compact_seconds, 2),
        "chunks_merged": merged,
        "grid_read_ms": round(read_seconds * 1000, 1),
        "raw_read_ms": round(raw_seconds * 1000, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--points", type=int, default=2000)
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--deviation", type=float, default=0.1)
    parser.add_argument("--database-url", default="", help="PostgreSQL instead of SQLite")
    args = parser.parse_args(argv)
    if args.database_url:
        with scratch_schema(args.database_url) as url:
            result = run(args.points, args.seconds, args.deviation, url)
    else:
        with tempfile.TemporaryDirectory() as folder:
            result = run(
                args.points, args.seconds, args.deviation, Path(folder) / "archive.sqlite3"
            )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
