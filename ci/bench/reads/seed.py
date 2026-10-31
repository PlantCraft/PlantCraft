"""Seed a Historian archive (PostgreSQL) with N points x D days through the real write path.

    python seed.py --db postgresql://postgres@/hist?host=/tmp&port=55432 --points 2000 --days 2 --thin 1

Values: gen.Templates (hour-long streams of the Historian's real Compressor, Standard profile,
~0.18 archived values/s/point); --thin k keeps one value in k (demo-like density: --thin 10).
Written one chunk per point per hour (as the collector's settle leaves them after the hourly
compaction), then compacted by tiers like housekeeping: closed days become day chunks, the
current day stays in hour chunks.
"""

import argparse
import json
import time

import numpy as np
from gen import Templates, kinds
from histcraft.archive.store import ArchiveStore
from histcraft.catalog.store import CatalogStore, PointIn, SourceIn
from histcraft.db import Database

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--points", type=int, default=2000)
ap.add_argument("--days", type=float, default=2)
ap.add_argument("--thin", type=int, default=1)
ap.add_argument("--source", default="bench")
a = ap.parse_args()

catalog = CatalogStore(Database(a.db))
archive = ArchiveStore(Database(a.db))
try:
    catalog.source(a.source)
except Exception:
    catalog.save_source(
        SourceIn(
            id=a.source,
            name="Bench",
            kind="opcua",
            enabled=False,
            endpoint="opc.tcp://bench.invalid:4840/",
            namespace_uri="urn:bench",
        ),
        create=True,
    )
k = kinds(a.points)
names = ["PV", "TI", "OP", "SP", "XS"]
items = [
    PointIn(
        tag=f"P{n:05d}.{names[k[n]]}",
        source_id=a.source,
        unit="%",
        low=0,
        high=100,
        step=bool(k[n] in (3, 4)),
    )
    for n in range(a.points)
]
catalog.add_points(items)
points = sorted(catalog.points(source_id=a.source), key=lambda p: p["tag"])
ids = np.array([int(p["id"]) for p in points])
archive.delete_points(ids.tolist())
t0 = time.perf_counter()
tpl = Templates(n=300, hours=2)
print("templates", round(time.perf_counter() - t0, 1), "s, rate", round(tpl.rate, 3), flush=True)
rng = np.random.default_rng(3)
levels = rng.uniform(20, 80, a.points)
hours = int(a.days * 24)
now_ms = int(time.time()) // 3600 * 3_600_000
start = now_ms - hours * 3_600_000
written = 0
t0 = time.perf_counter()
for h in range(hours):
    hour_ms = start + h * 3_600_000
    p, t, v = tpl.hour(np.arange(a.points), k, levels, h, hour_ms)
    batch = {}
    cut = np.flatnonzero(np.diff(p)) + 1
    for idx, tt, vv in zip(np.split(p, cut), np.split(t, cut), np.split(v, cut)):
        if a.thin > 1:
            tt, vv = tt[:: a.thin], vv[:: a.thin]
        batch[int(ids[idx[0]])] = ("number", list(zip(tt.tolist(), vv.tolist())))
    written += archive.append(batch)
    if h % 6 == 0:
        print("hour", h, written, round(time.perf_counter() - t0, 1), flush=True)
t1 = time.perf_counter()
merged = archive.compact(now_ms - 3_600_000 * 0 + 1)
print(
    json.dumps(
        {
            "points": a.points,
            "days": a.days,
            "thin": a.thin,
            "values": written,
            "per_point_day": round(written / a.points / a.days),
            "write_s": round(t1 - t0, 1),
            "compact_s": round(time.perf_counter() - t1, 1),
            "merged": merged,
        }
    )
)
