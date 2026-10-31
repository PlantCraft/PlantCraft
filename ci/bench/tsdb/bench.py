"""A4 bench: load the A1.4 dataset into one database and run the same reads against it.

    python ci/bench/tsdb/bench.py load  --engine clickhouse --days 7   # last 7 days, 2,000 points
    python ci/bench/tsdb/bench.py query --engine clickhouse            # Q1..Q7, warm and cold
    python ci/bench/tsdb/bench.py conc  --engine clickhouse            # Q2 at 1, 2, 4, 8, 16 at once
    python ci/bench/tsdb/bench.py check --engine clickhouse            # values read == values loaded
    python ci/bench/tsdb/bench.py stop  --engine clickhouse

Reads (end = the end of the loaded data):
  Q1 trend        1 point (pv), 24 h, raw values
  Q2 round        200 points, 24 h, raw values: one Analytics "Control loop performance" read
  Q3 fleet        2,000 points, 24 h, raw values
  Q4 grid         200 points, 24 h, 60 s means computed by the database
  Q5 long trend   1 point, whole loaded span, 1 h means
  Q6 incremental  200 points, last 15 min, raw (what an incremental Analytics round would read)
  Q7 last         2,000 points, newest value
Every result is turned into numpy arrays in this process; the time includes that.
Results: one JSON line per run in $TSDB_OUT (default /var/tmp/tsdb/results.jsonl).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dataset  # noqa: E402
import engines  # noqa: E402

DATA = Path(os.environ.get("TSDB_DATA", "/var/tmp/tsdb/data"))
OUT = Path(os.environ.get("TSDB_OUT", "/var/tmp/tsdb/results.jsonl"))
STATE = Path(os.environ.get("TSDB_STATE", "/var/tmp/tsdb/state.json"))
MACHINE = os.environ.get("TSDB_MACHINE", "nuvem-4c16g")
HOUR = 3_600_000
DAY = 24 * HOUR


def record(row: dict):
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": MACHINE,
        "cpus": engines.CPUS,
        "memory": engines.MEMORY,
        **row,
    }
    print(json.dumps(row), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(row) + "\n")


def state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s: dict):
    STATE.write_text(json.dumps(s))


def pct(xs, q):
    return float(np.percentile(xs, q)) if len(xs) else None


def drop_caches():
    try:
        subprocess.run(["sync"], check=False)
        Path("/proc/sys/vm/drop_caches").write_text("3\n")
        return True
    except OSError:
        return False


def to_pandas(got: dict) -> dict:
    """What ``series_many_pandas`` hands Analytics: one Series per signal, UTC DatetimeIndex."""
    import pandas as pd

    return {
        p: (pd.Series(v, index=pd.to_datetime(t, unit="ms", utc=True)),)
        for p, (t, v) in got.items()
    }


def fleet(eng, ids, t0, t1, batch=2000):
    """Every signal, read 2,000 at a time and dropped after counting (10k x 24 h is ~2.5 GB)."""
    total = 0
    for i in range(0, len(ids), batch):
        total += sum(len(t) for t, _ in eng.raw_many(ids[i : i + batch], t0, t1).values())
    return {0: (range(total),)}


def round_ids(n=200, seed=5, total=dataset.POINTS):
    return sorted(
        int(x)
        for x in np.random.default_rng(seed).choice(
            np.arange(1, total + 1), min(n, total), replace=False
        )
    )


# ---------------------------------------------------------------------------------------------


def load(key: str, days: int, points: int = dataset.POINTS):
    eng = engines.ENGINES[key]()
    eng.start()
    time.sleep(3)
    idle = eng.ram()
    first = dataset.YEAR_DAYS - days
    dataset.write(DATA, first, days, points)
    w0 = time.perf_counter()
    values = 0
    per_day = []
    for d in range(first, first + days):
        p, t, v = dataset.read(DATA, d, points)
        d0 = time.perf_counter()
        eng.load_day(p, t, v)
        per_day.append(time.perf_counter() - d0)
        values += len(p)
        print(
            f"{key}: day {d} loaded in {per_day[-1]:.1f} s ({values:,} values)",
            file=sys.stderr,
            flush=True,
        )
    load_s = time.perf_counter() - w0
    f0 = time.perf_counter()
    eng.finish()
    finish_s = time.perf_counter() - f0
    time.sleep(5)
    size = eng.size()
    s = state()
    s[key] = {
        "first": first,
        "days": days,
        "points": points,
        "values": values,
        "t0": dataset.day_start(first),
        "t1": dataset.day_start(first + days),
    }
    save_state(s)
    record(
        {
            "test": "load",
            "engine": eng.name,
            "key": key,
            "version": eng.version(),
            "days": days,
            "points": points,
            "values": values,
            "load_s": load_s,
            "values_per_s": values / load_s,
            "finish_s": finish_s,
            "day_s_max": max(per_day),
            "bytes": size,
            "bytes_per_value": size / values,
            "ram_idle_empty": idle,
            "ram_after_load": eng.ram(),
            "image_bytes": eng.image_bytes(),
        }
    )


def queries(key: str, repeat: int = 7):
    eng = engines.ENGINES[key]()
    s = state()[key]
    t1 = s["t1"]
    t0 = s["t0"]
    rng = np.random.default_rng(11)
    npts = s.get("points", dataset.POINTS)
    ids = round_ids(total=min(npts, dataset.POINTS))
    all_ids = list(range(1, npts + 1))
    pv = [i for i in all_ids if dataset.kinds(npts)[i - 1] == 0]
    qs = {
        "Q1 tendência 1 ponto 24 h bruto": lambda: eng.raw_many(
            [int(rng.choice(pv))], t1 - DAY, t1
        ),
        "Q2 rodada 200 pontos 24 h bruto": lambda: eng.raw_many(ids, t1 - DAY, t1),
        "Q2s rodada só no servidor (contar e somar)": lambda: {
            0: (np.zeros(int(eng.scan(ids, t1 - DAY, t1))),)
        },
        "Q2p rodada 200 pontos 24 h + pandas": lambda: to_pandas(eng.raw_many(ids, t1 - DAY, t1)),
        f"Q3 frota {npts} pontos 24 h bruto": lambda: fleet(eng, all_ids, t1 - DAY, t1),
        "Q4 grade 200 pontos 24 h 60 s": lambda: eng.grid(ids, t1 - DAY, t1, 60_000),
        "Q5 tendência longa 1 ponto 1 h": lambda: eng.grid([int(rng.choice(pv))], t0, t1, HOUR),
        "Q6 incremental 200 pontos 15 min": lambda: eng.raw_many(ids, t1 - 15 * 60_000, t1),
        f"Q7 último valor {npts} pontos": lambda: eng.last(all_ids),
        "Q8 1 ponto período todo bruto": lambda: eng.raw_many([int(rng.choice(pv))], t0, t1),
    }
    out = {}
    for name, fn in qs.items():
        n = 3 if name.startswith("Q3") else repeat
        cold = drop_caches()
        times, err, values = [], None, 0
        for i in range(n + 1):
            w = time.perf_counter()
            try:
                got = fn()
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {str(exc)[:300]}"
                break
            times.append(time.perf_counter() - w)
            values = sum(
                len(x[0]) if isinstance(x, tuple) and hasattr(x[0], "__len__") else 1
                for x in got.values()
            )
        out[name] = {
            "cold_ms": times[0] * 1000 if times and cold else None,
            "first_ms": times[0] * 1000 if times else None,
            "p50_ms": pct(times[1:], 50) * 1000 if len(times) > 1 else None,
            "p95_ms": pct(times[1:], 95) * 1000 if len(times) > 1 else None,
            "values": values,
            "error": err,
        }
        print(name, json.dumps(out[name]), file=sys.stderr, flush=True)
    record(
        {
            "test": "query",
            "engine": eng.name,
            "key": key,
            "days": s["days"],
            "values_loaded": s["values"],
            "queries": out,
        }
    )


def _worker(args):
    key, t1, ids, rounds, barrier = args
    eng = engines.ENGINES[key]()
    eng.raw_many(ids[:5], t1 - HOUR, t1)  # connect
    barrier.wait()
    times = []
    for _ in range(rounds):
        w = time.perf_counter()
        eng.raw_many(ids, t1 - DAY, t1)
        times.append(time.perf_counter() - w)
    return times


def conc(key: str, levels=(1, 2, 4, 10, 16), rounds: int = 3):
    eng = engines.ENGINES[key]()
    s = state()[key]
    t1 = s["t1"]
    rows = {}
    for n in levels:
        # each client reads its own 200 signals (different loops), as parallel Analytics rounds do
        mgr = mp.Manager()
        barrier = mgr.Barrier(n)
        args = [
            (
                key,
                t1,
                round_ids(
                    200, seed=100 + i, total=min(s.get("points", dataset.POINTS), dataset.POINTS)
                ),
                rounds,
                barrier,
            )
            for i in range(n)
        ]
        w = time.perf_counter()
        with mp.get_context("spawn").Pool(n) as pool:
            res = pool.map(_worker, args)
        wall = time.perf_counter() - w
        flat = [x for r in res for x in r]
        rows[str(n)] = {
            "p50_s": pct(flat, 50),
            "p95_s": pct(flat, 95),
            "rounds_per_s": len(flat) / max(sum(r) for r in res),
            "wall_s": wall,
        }
        print(key, n, json.dumps(rows[str(n)]), file=sys.stderr, flush=True)
        if rows[str(n)]["p50_s"] > 20:
            break  # past 20 s a round, more clients only queue
    record(
        {
            "test": "conc",
            "engine": eng.name,
            "key": key,
            "days": s["days"],
            "query": "Q2 rodada 200 pontos 24 h",
            "levels": rows,
        }
    )


def check(key: str):
    eng = engines.ENGINES[key]()
    s = state()[key]
    d = s["first"] + s["days"] - 1
    p, t, v = dataset.read(DATA, d, s["points"])
    ids = round_ids(20, total=min(s["points"], dataset.POINTS))
    t0, t1 = dataset.day_start(d), dataset.day_start(d + 1)
    got = eng.raw_many(ids, t0, t1)
    bad = []
    for pt in ids:
        m = p == pt
        tt, vv = t[m], v[m]
        gt, gv = got.get(pt, (np.zeros(0), np.zeros(0)))
        if (
            len(gt) != len(tt)
            or not np.array_equal(gt, tt)
            or not np.allclose(gv, vv, rtol=0, atol=0)
        ):
            diff = float(np.max(np.abs(gv - vv))) if len(gv) == len(vv) and len(vv) else None
            bad.append({"point": pt, "expected": len(tt), "got": len(gt), "max_abs_diff": diff})
    record(
        {
            "test": "check",
            "engine": eng.name,
            "key": key,
            "points": len(ids),
            "exact": not bad,
            "bad": bad[:5],
        }
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["load", "query", "conc", "check", "stop", "all"])
    ap.add_argument("--engine", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--points", type=int, default=dataset.POINTS)
    ap.add_argument("--repeat", type=int, default=7)
    a = ap.parse_args()
    if a.cmd in ("load", "all"):
        load(a.engine, a.days, a.points)
    if a.cmd in ("check", "all"):
        check(a.engine)
    if a.cmd in ("query", "all"):
        queries(a.engine, a.repeat)
    if a.cmd in ("conc", "all"):
        conc(a.engine)
    if a.cmd == "stop":
        engines.ENGINES[a.engine]().stop()
