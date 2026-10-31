"""A1.4: the standard dataset every time-series bench of the 2026-10-31 plan reads.

2,000 points x 1 year of *archived* values (what the Historian keeps after its own compression),
deterministic, built one day at a time so any subset can be loaded without storing the year:

    python ci/bench/tsdb/dataset.py write --days 7 --out /var/tmp/tsdb/data     # last 7 days
    python ci/bench/tsdb/dataset.py write --first 0 --days 365 --points 100 ...  # a year, 100 points
    python ci/bench/tsdb/dataset.py info

Signals: 40 % noisy process values (pv), 20 % temperatures, 15 % valve outputs, 15 % set points,
10 % digital states, span 0-100. One-hour streams of 500 real signals are run through the
Historian's real Compressor (Standard profile: exception 0.1 %, deviation 0.2 % of span, 10 min
max interval) and tiled in time, shifted in level: real intervals, real value patterns,
~0.18 archived values per second per point (pv points ~0.4/s), 15.5 k values per point per day.

Day ``d`` (0..364) covers [T_END - (365 - d) days, T_END - (364 - d) days); the year ends at
T_END = 2026-10-31 00:00 UTC. Day files are Parquet (zstd) with columns point int32, t int64 (ms
UTC), v float64, sorted by (point, t). Point ids are 1..2000, kind by id (``kinds``).
Same seeds give the same values on every machine: two benches can load the same days.
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path[:0] = [str(REPO / "apps/historian/src"), str(REPO / "sdk/python")]
from histcraft.archive.compression import Compressor  # noqa: E402

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
T_END = 1_793_404_800_000  # 2026-10-31 00:00 UTC
YEAR_DAYS = 365
POINTS = 2000
TYPES = ("pv", "temp", "valve", "setpoint", "digital")
SHARE = (0.40, 0.20, 0.15, 0.15, 0.10)
SPAN = 100.0


def day_start(day: int) -> int:
    return T_END - (YEAR_DAYS - day) * DAY_MS


def kinds(points: int = POINTS) -> np.ndarray:
    """Kind index (into TYPES) of points 1..points, interleaved so any id range mixes kinds."""
    # Interleave: id i gets kind by position in a repeating 20-slot pattern (8 pv, 4 temp,
    # 3 valve, 3 setpoint, 2 digital), so the first 200 ids of a 2000-point plant look like it.
    pattern = np.repeat(np.arange(5), [8, 4, 3, 3, 2])
    return pattern[np.arange(points) % 20]


def levels(points: int = POINTS) -> np.ndarray:
    return np.random.default_rng(3).uniform(20, 80, points)


class Raw:
    """One value per point per scan (float32 like a PLC REAL), state carried between blocks."""

    def __init__(self, k: np.ndarray, seed: int = 1):
        self.rng = np.random.default_rng(seed)
        self.k = k
        self.n = len(k)
        self.level = self.rng.uniform(20, 80, self.n)
        self.target = self.level.copy()

    def block(self, scans: int, scan_s: float = 1.0) -> np.ndarray:
        r, k, n = self.rng, self.k, self.n
        out = np.empty((scans, n), dtype=np.float64)
        p_step = np.choose(
            k, [scan_s / 3600, scan_s / 3600, scan_s / 3600, scan_s / 7200, scan_s / 1800]
        )
        walk = np.choose(k, [0.02, 0.002, 0.05, 0.0, 0.0]) * np.sqrt(scan_s)
        lag = np.choose(k, [0.02, 0.003, 0.05, 1.0, 1.0])
        noise = np.choose(k, [0.15, 0.02, 0.05, 0.0, 0.0])
        for i in range(scans):
            step = r.random(n) < p_step
            new = r.uniform(20, 80, n)
            new = np.where(k == 4, np.where(self.target > 50, 0.0, 100.0), new)
            self.target = np.where(step, new, self.target)
            self.level += lag * (self.target - self.level) + r.normal(0, 1, n) * walk
            out[i] = (self.level + r.normal(0, 1, n) * noise).astype(np.float32)
        return out


class Templates:
    """One-hour archived streams of real compressed signals, times relative to the hour."""

    def __init__(self, n: int = 500, hours: int = 2, seed: int = 7):
        k = kinds(n)
        raw = Raw(k, seed)
        comps = [
            Compressor(
                deviation=0.002 * SPAN,
                exception=0.001 * SPAN,
                max_seconds=600,
                step=bool(k[i] in (3, 4)),
            )
            for i in range(n)
        ]
        ts: list[list[int]] = [[] for _ in range(n)]
        vs: list[list[float]] = [[] for _ in range(n)]
        done = 0
        while done < hours * 3600:
            vals = raw.block(600)
            for i in range(600):
                at = (done + i) * 1000
                row = vals[i]
                for p in range(n):
                    for t, v in comps[p].feed(at, float(row[p])):
                        ts[p].append(t)
                        vs[p].append(v)
            done += 600
        self.items: list[list[tuple[np.ndarray, np.ndarray]]] = [[] for _ in TYPES]
        for p in range(n):
            t, v = np.array(ts[p], dtype=np.int64), np.array(vs[p])
            for h in range(hours):
                m = (t >= h * HOUR_MS) & (t < (h + 1) * HOUR_MS)
                if m.any():
                    self.items[k[p]].append((t[m] - h * HOUR_MS, v[m] - v[m].mean()))

    @classmethod
    def cached(cls, path: Path) -> "Templates":
        if path.exists():
            tpl = cls.__new__(cls)
            with open(path, "rb") as f:
                tpl.items = pickle.load(f)
            return tpl
        tpl = cls()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(tpl.items, f)
        return tpl


def day(tpl: Templates, d: int, points: int = POINTS, first_point: int = 1):
    """(point int32, t int64 ms, v float64) of day ``d`` for ids first_point.., sorted by (point, t)."""
    k_all, lev_all = kinds(POINTS), levels(POINTS)
    t0 = day_start(d)
    ps, ts, vs = [], [], []
    for pid in range(first_point, first_point + points):
        k, lev = k_all[pid - 1], lev_all[pid - 1]
        lst = tpl.items[k]
        drift = 5.0 * np.sin(2 * np.pi * (d + pid % 97) / 61.0)  # slow seasonal drift, per point
        for h in range(24):
            hour = d * 24 + h
            tt, vv = lst[(pid * 7 + hour * 13) % len(lst)]
            ts.append(tt + t0 + h * HOUR_MS)
            if k == 4:
                vs.append(np.where(vv > 0, 100.0, 0.0))
            elif k == 3:
                vs.append(np.round(vv + lev + drift, 1))
            else:
                vs.append((vv + lev + drift).astype(np.float32).astype(np.float64))
            ps.append(np.full(len(tt), pid, dtype=np.int32))
    return np.concatenate(ps), np.concatenate(ts), np.concatenate(vs)


def write(out: Path, first: int, days: int, points: int) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    out.mkdir(parents=True, exist_ok=True)
    tpl = None
    for d in range(first, first + days):
        path = out / f"p{points}-d{d:03d}.parquet"
        if path.exists():
            continue
        tpl = tpl or Templates.cached(out / "templates.pkl")
        p, t, v = day(tpl, d, points)
        pq.write_table(
            pa.table({"point": p, "t": t, "v": v}),
            path,
            compression="zstd",
            row_group_size=1_000_000,
        )
        print(f"{path.name}: {len(p):,} values", file=sys.stderr)


def read(out: Path, d: int, points: int = POINTS):
    import pyarrow.parquet as pq

    tab = pq.read_table(out / f"p{points}-d{d:03d}.parquet")
    return (tab["point"].to_numpy(), tab["t"].to_numpy(), tab["v"].to_numpy())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["write", "info"])
    ap.add_argument("--out", default=os.environ.get("TSDB_DATA", "/var/tmp/tsdb/data"))
    ap.add_argument("--first", type=int, default=YEAR_DAYS - 7)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--points", type=int, default=POINTS)
    a = ap.parse_args()
    if a.cmd == "write":
        write(Path(a.out), a.first, a.days, a.points)
    else:
        tpl = Templates.cached(Path(a.out) / "templates.pkl")
        p, t, v = day(tpl, YEAR_DAYS - 1)
        per_kind = {
            TYPES[k]: int(np.sum(kinds()[p - 1] == k)) / int(np.sum(kinds() == k)) for k in range(5)
        }
        print(
            f"values per day (2000 points): {len(p):,}; per point per s {len(p) / POINTS / 86400:.3f}"
        )
        print("values per point per day by kind:", {k: round(x) for k, x in per_kind.items()})
