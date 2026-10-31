"""A1.1/A1.2: where the time of one round's read goes, stage by stage, in one process.

    python breakdown.py --db URL --source demo200 --signals 200 --hours 24 [--parts 4]

Server side (the Historian's POST /api/v1/series, read_batch): catalog, SQL, chunk decode +
assemble, series() (filter + ISO text), JSON encode. Client side (the SDK + Analytics):
json.loads, parse_times + float arrays (series_to_pandas), the wide frame (PlantData.read_range).
--parts splits the signals as Analytics does (4 requests of >= 40 signals); stages are summed.
"""

import argparse
import json
import pathlib
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd
from histcraft.api.read_budget import EncodedBatch
from histcraft.api.routers import data
from histcraft.api.runtime import Runtime
from histcraft.archive import query as query_mod
from histcraft.archive import store as store_mod
from histcraft.config import Settings

from plantcraft_sdk.contract import series_to_pandas
from plantcraft_sdk.testing import BASE_URL, FakePlantCraft

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--source", default="demo200")
ap.add_argument("--signals", type=int, default=200)
ap.add_argument("--hours", type=float, default=24)
ap.add_argument("--parts", type=int, default=4)
ap.add_argument("--repeat", type=int, default=3)
a = ap.parse_args()

T = defaultdict(float)


def timed(name, fn):
    def wrap(*args, **kw):
        t0 = time.perf_counter()
        try:
            return fn(*args, **kw)
        finally:
            T[name] += time.perf_counter() - t0

    return wrap


fake = FakePlantCraft(users={"admin": {"name": "A", "level": "admin", "apps": {}}})
settings = Settings(
    processcraft_url=BASE_URL,
    data_dir=pathlib.Path("/home/user/bench/var"),
    collector="off",
    database_url=a.db,
)
rt = Runtime(settings, verifier=fake.verifier("histcraft"), http_client=fake.http_client())
# Stage wrappers.
rt.catalog.find_many = timed("1 catalog", rt.catalog.find_many)
store_mod._assemble = timed("3 decode+assemble", store_mod._assemble)
orig_read_many = rt.archive.read_many


def read_many(*args, **kw):
    t0 = time.perf_counter()
    before = T["3 decode+assemble"]
    out = orig_read_many(*args, **kw)
    T["2 SQL (fetch chunks)"] += time.perf_counter() - t0 - (T["3 decode+assemble"] - before)
    return out


rt.archive.read_many = read_many
rt.archive.snapshots = timed("2b snapshots", rt.archive.snapshots)
query_mod.iso_ms = timed("4b ISO text", query_mod.iso_ms)
orig_series = rt.reader.series


def series(*args, **kw):
    t0 = time.perf_counter()
    before = T["4b ISO text"]
    out = orig_series(*args, **kw)
    T["4a series() filter"] += time.perf_counter() - t0 - (T["4b ISO text"] - before)
    return out


rt.reader.series = series
EncodedBatch.add = timed("5 JSON encode", EncodedBatch.add)

points = sorted(rt.catalog.points(source_id=a.source), key=lambda p: p["tag"])[: a.signals]
names = [p["signal"] for p in points]
end = datetime.now(timezone.utc).replace(microsecond=0)
start = end - timedelta(hours=a.hours)
size = -(-len(names) // a.parts)
parts = [names[i : i + size] for i in range(0, len(names), size)]
runs = []
for r in range(a.repeat + 1):
    T.clear()
    t_all = time.perf_counter()
    bodies = []
    for part in parts:
        body = data.BatchIn(signals=part, start=start.isoformat(), end=end.isoformat())
        with rt.read_budget.hold() as ticket:
            builder = data.read_batch(body, rt, ticket)
            t0 = time.perf_counter()
            bodies.append(builder.response().body)
            T["5 JSON encode"] += time.perf_counter() - t0
    server = time.perf_counter() - t_all
    nbytes = sum(len(b) for b in bodies)
    values = 0
    t0 = time.perf_counter()
    decoded = [json.loads(b) for b in bodies]
    T["6 client json.loads"] += time.perf_counter() - t0
    t0 = time.perf_counter()
    cols = {}
    for d in decoded:
        for item in d["series"]:
            cols[item["signal"]] = series_to_pandas(item)
            values += len(item["v"])
    T["7 client to pandas"] += time.perf_counter() - t0
    t0 = time.perf_counter()
    shaped = {}
    for k, v in cols.items():
        v = v.copy()
        v.index = v.index.tz_convert("UTC").tz_localize(None)
        v = v.dropna()
        shaped[k] = v[~v.index.duplicated(keep="last")]
    frame = pd.concat(shaped, axis=1).sort_index()
    T["8 client wide frame"] += time.perf_counter() - t0
    total = time.perf_counter() - t_all
    if r:
        runs.append(
            {
                "total": total,
                "server": server,
                "stages": dict(T),
                "bytes": nbytes,
                "values": values,
                "frame": frame.shape,
            }
        )
med = lambda key: statistics.median(run["stages"].get(key, 0) for run in runs)
keys = sorted({k for run in runs for k in run["stages"]})
out = {
    "source": a.source,
    "signals": len(names),
    "hours": a.hours,
    "values": runs[0]["values"],
    "MB": round(runs[0]["bytes"] / 1e6, 1),
    "frame": list(runs[0]["frame"]),
    "total_s": round(statistics.median(r["total"] for r in runs), 3),
    "stages_s": {k: round(med(k), 3) for k in keys},
}
print(json.dumps(out))
