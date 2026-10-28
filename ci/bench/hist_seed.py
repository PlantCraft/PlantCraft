"""The bench plant in HistCraft; run inside its container by ci/bench/suite_bench.py.

    docker compose exec -T -e LOOPS=2000 -e EXTRA=2000 -e HOURS=6 histcraft python - < hist_seed.py

Adds source ``bench`` (OPC UA, disabled: the collector never polls it) with LOOPS x PV/SP/OP and
EXTRA signals, and archives HOURS of values, one every STEP_S (30) s, through the real compressors (0.1 %
deviation, each point's max interval), written each simulated minute as the collector writes, then compacted. Prints one
JSON line with the counts and times. ``CLEANUP=1`` removes the source, its signals and archive, and the results LinkCraft published
for the bench loops.
"""

import json
import os
import re
import time

import numpy as np
from histcraft.archive.compression import Compressor
from histcraft.archive.store import ArchiveStore
from histcraft.catalog.store import CatalogStore, PointIn, SourceIn
from histcraft.config import Settings
from histcraft.db import Database

SOURCE = "bench"
LOOPS = int(os.environ.get("LOOPS", 2000))
EXTRA = int(os.environ.get("EXTRA", 2000))
HOURS = float(os.environ.get("HOURS", 6))
STEP_S = int(os.environ.get("STEP_S", 30))
BENCH_SERIES = re.compile(rf"(LC-\d{{5}}\.|{SOURCE}:)")

settings = Settings.from_environment()
password = settings.database_password()
catalog = CatalogStore(Database(settings.config_target, password=password))
archive = ArchiveStore(Database(settings.archive_target, password=password))


def cleanup() -> None:
    bench = catalog.points(source_id=SOURCE)
    # LinkCraft publishes under its own source each bench loop's results (LC-nnnnn.health,
    # LC-nnnnn.status) and each bench signal's data quality (bench:LC-nnnnn.PV.quality, ...).
    link = [
        point
        for point in catalog.points(source_id="app-linkcraft")
        if BENCH_SERIES.match(point["tag"])
    ]
    ids = [int(point["id"]) for point in bench + link]
    if link:  # out of the catalog for good: retired, then purged at once
        catalog.purge_retired(catalog.retire_points([p["signal"] for p in link], by="bench"))
    if any(source["id"] == SOURCE for source in catalog.sources()):
        catalog.delete_source(SOURCE, with_points=True)
    archive.delete_points(ids)
    print(json.dumps({"cleanup": "done", "bench": len(bench), "linkcraft": len(link)}))


def seed() -> None:
    began = time.perf_counter()
    try:
        catalog.source(SOURCE)
    except Exception:  # noqa: BLE001 - not there yet
        catalog.save_source(
            SourceIn(
                id=SOURCE,
                name="Scale bench",
                kind="opcua",
                enabled=False,
                endpoint="opc.tcp://bench.invalid:4840/",
                namespace_uri="urn:bench",
            ),
            create=True,
        )
    items = [
        PointIn(tag=f"LC-{n:05d}.{role}", source_id=SOURCE, unit="%", low=0, high=100)
        for n in range(LOOPS)
        for role in ("PV", "SP", "OP")
    ]
    items += [
        PointIn(tag=f"AI-{n:05d}", source_id=SOURCE, unit="bar", low=0, high=100)
        for n in range(EXTRA)
    ]
    catalog.add_points(items)
    points = catalog.points(source_id=SOURCE)
    archive.delete_points([int(point["id"]) for point in points])  # a run again starts empty
    catalog_seconds = time.perf_counter() - began
    count = len(points)
    ids = [int(point["id"]) for point in points]
    is_sp = np.array([point["tag"].endswith(".SP") for point in points])
    rng = np.random.default_rng(7)
    level = rng.uniform(20, 80, count)
    setpoint = level.copy()
    end_ms = int(time.time()) // 60 * 60_000
    seconds = int(HOURS * 3600)
    start_ms = end_ms - seconds * 1000
    # Each point's own maximum interval, as the collector uses it (general default otherwise).
    compressors = [
        Compressor(deviation=0.1, max_seconds=float(point.get("max_seconds") or 600))
        for point in points
    ]
    pending = [[] for _ in range(count)]
    written = 0
    write_seconds = 0.0
    began = time.perf_counter()
    for second in range(0, seconds, STEP_S):
        level += rng.normal(0, 0.05, count)
        values = np.where(is_sp, setpoint, level + rng.normal(0, 0.3, count))
        at = start_ms + second * 1000
        for index in range(count):
            out = compressors[index].feed(at, float(values[index]))
            if out:
                pending[index].extend(out)
        if (second // STEP_S + 1) % max(1, 60 // STEP_S) == 0:
            flushed = time.perf_counter()
            written += archive.append({ids[i]: ("number", p) for i, p in enumerate(pending) if p})
            write_seconds += time.perf_counter() - flushed
            pending = [[] for _ in range(count)]
    for index in range(count):
        pending[index].extend(compressors[index].flush())
    flushed = time.perf_counter()
    written += archive.append({ids[i]: ("number", p) for i, p in enumerate(pending) if p})
    write_seconds += time.perf_counter() - flushed
    archive_seconds = time.perf_counter() - began
    began = time.perf_counter()
    merged = archive.compact(end_ms + 1)
    compact_seconds = time.perf_counter() - began
    print(
        json.dumps(
            {
                "points": count,
                "catalog_seconds": round(catalog_seconds, 1),
                "fed": count * (seconds // STEP_S),
                "archived": written,
                "archive_seconds": round(archive_seconds, 1),
                "database_write_seconds": round(write_seconds, 1),
                "values_per_second": round(written / max(write_seconds, 1e-9)),
                "compact_seconds": round(compact_seconds, 1),
                "chunks_merged": merged,
                "database": archive.db.dialect,
            }
        )
    )


if os.environ.get("CLEANUP"):
    cleanup()
else:
    seed()
