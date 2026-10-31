"""What one Analytics round batch costs before its loops reach the process pool (2026-10-31).

50 loops x 4 signals (pv, sp, op, mode), 24 h of raw samples at irregular times (one value every
~30 s per signal, like an exception-recorded plant). ``batch``: one frame of the batch, then
``raw[columns]`` per loop (0.5.x to SDK 0.91). ``loop``: each loop's frame from its own series.
Measures the time to build the tasks, their pickled size (what the pool ships) and the peak
Python memory, and checks that the default algorithm gives the same summary both ways.

    python ci/bench/reads/roundframes.py [--loops 50] [--every 30] [--check 5]
"""

import argparse
import pickle
import time
import tracemalloc

import numpy as np
import pandas as pd
from linkcraft.config import AnalysisConfig, LoopConfig
from linkcraft.data.frames import loop_signal_ids
from linkcraft.data.plant import Signals, wide_frame
from linkcraft.loops.analysis import analyze_loop


def series(rng, start, seconds, every, kind):
    gaps = rng.exponential(every, int(seconds / every * 1.2))
    stamps = start + pd.to_timedelta(np.cumsum(gaps), unit="s")
    stamps = stamps[stamps < start + pd.Timedelta(seconds=seconds)]
    stamps = pd.DatetimeIndex(stamps).as_unit("ns").floor("ms").unique()
    if kind == "mode":
        return pd.Series(
            np.where(rng.random(len(stamps)) < 0.95, "AUTO", "MAN"), stamps, dtype=object
        )
    walk = 50 + np.cumsum(rng.normal(0, 0.2, len(stamps)))
    return pd.Series(walk if kind != "sp" else np.round(walk / 5) * 5, stamps)


def build(loops, every, seed=7):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-10-30")
    configs, data = [], {}
    for n in range(loops):
        ids = {role: f"plant:L{n:03d}.{role}" for role in ("pv", "sp", "op", "mode")}
        configs.append(LoopConfig(loop_id=f"L{n:03d}", name=f"L{n:03d}", signals=ids))
        for role, signal in ids.items():
            data[signal] = series(rng, start, 86400, every, role)
    return configs, Signals(data, [])


def tasks_batch(configs, signals):
    raw = wide_frame(dict(signals))
    out = []
    for loop in configs:
        columns = [c for c in loop_signal_ids(loop) if c in raw.columns]
        out.append(raw[columns])
    return out, raw.shape, float(raw.isna().to_numpy().mean())


def tasks_loop(configs, signals):
    return [signals.frame(loop_signal_ids(loop)) for loop in configs], None, None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loops", type=int, default=50)
    ap.add_argument("--every", type=float, default=30.0)
    ap.add_argument("--check", type=int, default=5)
    a = ap.parse_args()
    configs, signals = build(a.loops, a.every)
    frames = {}
    for name, how in (("batch", tasks_batch), ("loop", tasks_loop)):
        tracemalloc.start()
        t0 = time.perf_counter()
        raws, shape, empty = how(configs, signals)
        shipped = sum(len(pickle.dumps(raw, protocol=5)) for raw in raws)
        took = time.perf_counter() - t0
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        frames[name] = raws
        print(
            f"{name:5s} build+pickle {took:6.2f} s  shipped {shipped / 1e6:7.1f} MB  "
            f"peak {peak / 1e6:7.1f} MB"
            + (f"  batch frame {shape[0]} x {shape[1]}, {empty:.1%} empty" if shape else "")
        )
    analysis = AnalysisConfig()
    same = 0
    for loop, old, new in list(zip(configs, frames["batch"], frames["loop"]))[: a.check]:
        t0 = time.perf_counter()
        before = analyze_loop(analysis, loop, old)["summary"]
        t1 = time.perf_counter()
        after = analyze_loop(analysis, loop, new)["summary"]
        t2 = time.perf_counter()
        keys = ("status", "health", "functional_score", "limiting")
        same += all(before.get(k) == after.get(k) for k in keys)
        print(
            f"{loop.loop_id}: analyse {t1 - t0:.2f} -> {t2 - t1:.2f} s, "
            f"health {before.get('health')} -> {after.get('health')}"
        )
    print(f"same summary on {same} of {min(a.check, len(configs))} loops")
