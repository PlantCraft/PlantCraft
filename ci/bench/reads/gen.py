"""Synthetic plant signals and their archived streams (the Historian's own compression).

Raw values: one per point per scan, float32-quantised like a PLC REAL, span 0-100 EU.
Mix: 40 % noisy process values, 20 % temperatures, 15 % valve outputs, 15 % set points,
10 % digital states. Archived values come from the Historian's real Compressor with the
Standard profile (exception 0.1 %, compression 0.2 % of span, 10 min max interval).
To build days of history cheaply, compressed one-hour streams of real signals are reused as
templates (tiled in time, shifted in level), keeping real intervals and value patterns.
"""

from __future__ import annotations

import numpy as np

pass
from histcraft.archive.compression import Compressor  # noqa: E402

TYPES = ("pv", "temp", "valve", "setpoint", "digital")
SHARE = (0.40, 0.20, 0.15, 0.15, 0.10)
SPAN = 100.0


def kinds(points: int) -> np.ndarray:
    edges = np.cumsum(SHARE) * points
    idx = np.arange(points)
    return np.searchsorted(edges, idx, side="right").clip(0, 4)


class Raw:
    """One value per point per scan, generated a block of scans at a time (state carried)."""

    def __init__(self, points: int, seed: int = 1):
        self.rng = np.random.default_rng(seed)
        self.k = kinds(points)
        self.n = points
        r = self.rng
        self.level = r.uniform(20, 80, points)
        self.target = self.level.copy()

    def block(self, scans: int, scan_s: float = 1.0) -> np.ndarray:
        """Array [scans, points]."""
        r, k, n = self.rng, self.k, self.n
        out = np.empty((scans, n), dtype=np.float64)
        for i in range(scans):
            # targets: rare steps (set points ~2 h, digital ~30 min, others drift targets ~1 h)
            p_step = np.choose(
                k, [scan_s / 3600, scan_s / 3600, scan_s / 3600, scan_s / 7200, scan_s / 1800]
            )
            step = r.random(n) < p_step
            new = r.uniform(20, 80, n)
            new = np.where(k == 4, np.where(self.target > 50, 0.0, 100.0), new)
            self.target = np.where(step, new, self.target)
            walk = np.choose(k, [0.02, 0.002, 0.05, 0.0, 0.0]) * np.sqrt(scan_s)
            lag = np.choose(k, [0.02, 0.003, 0.05, 1.0, 1.0])
            self.level += lag * (self.target - self.level) + r.normal(0, 1, n) * walk
            noise = np.choose(k, [0.15, 0.02, 0.05, 0.0, 0.0])
            v = self.level + r.normal(0, 1, n) * noise
            out[i] = v.astype(np.float32)
        return out


def compressors(points: int) -> list[Compressor]:
    k = kinds(points)
    return [
        Compressor(
            deviation=0.002 * SPAN,
            exception=0.001 * SPAN,
            max_seconds=600,
            step=bool(k[i] in (3, 4)),
        )
        for i in range(points)
    ]


def archive_stream(points: int, seconds: int, start_ms: int, seed: int = 1, scan_s: float = 1.0):
    """Run the real Compressor; returns list per point of (times_ms int64, values f64) and feeds."""
    raw = Raw(points, seed)
    comps = compressors(points)
    out_t: list[list[int]] = [[] for _ in range(points)]
    out_v: list[list[float]] = [[] for _ in range(points)]
    scans = int(seconds / scan_s)
    done = 0
    while done < scans:
        b = min(600, scans - done)
        vals = raw.block(b, scan_s)
        for i in range(b):
            at = start_ms + int((done + i) * scan_s * 1000)
            row = vals[i]
            for p in range(points):
                for t, v in comps[p].feed(at, float(row[p])):
                    out_t[p].append(t)
                    out_v[p].append(v)
        done += b
    return [
        (np.array(t, dtype=np.int64), np.array(v, dtype=np.float64)) for t, v in zip(out_t, out_v)
    ]


class Templates:
    """Hour-long archived streams of real compressed signals, relative times (ms in [0, 3.6e6))."""

    def __init__(self, n: int = 500, hours: int = 2, seed: int = 7):
        start = 0
        streams = archive_stream(n, hours * 3600, start, seed)
        self.kind = kinds(n)
        self.items: list[list[tuple[np.ndarray, np.ndarray]]] = [[] for _ in TYPES]
        for p, (t, v) in enumerate(streams):
            for h in range(hours):
                lo, hi = h * 3_600_000, (h + 1) * 3_600_000
                m = (t >= lo) & (t < hi)
                tt, vv = t[m] - lo, v[m]
                if len(tt) == 0:  # max interval guarantees at least ~6 per hour
                    continue
                self.items[self.kind[p]].append((tt, vv - vv.mean()))
        self.rate = sum(len(x[0]) for lst in self.items for x in lst) / (
            sum(len(lst) for lst in self.items) * 3600.0
        )

    def hour(
        self,
        points: np.ndarray,
        kinds_of: np.ndarray,
        levels: np.ndarray,
        hour_index: int,
        hour_ms: int,
    ):
        """Concatenated (point, t, v) for the given points over one hour starting at hour_ms."""
        ps, ts, vs = [], [], []
        for p, k, lev in zip(points, kinds_of, levels):
            lst = self.items[k]
            tt, vv = lst[(int(p) * 7 + hour_index * 13) % len(lst)]
            ps.append(np.full(len(tt), p, dtype=np.int32))
            ts.append(tt + hour_ms)
            vs.append((vv + lev).astype(np.float32).astype(np.float64))
        return np.concatenate(ps), np.concatenate(ts), np.concatenate(vs)
