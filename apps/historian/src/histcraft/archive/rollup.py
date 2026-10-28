"""Hourly rollups of the archive: per point and hour, the time with data (``cover``, ms) and
the integral of the rebuilt signal (``area``, value x ms), gap G9; and the lowest and highest
archived value of the hour (``low``, ``high``, None when it has none) and how many it holds
(``n``), for the min/max band of long trends and a window's min and max.

An hour is ``[hour, hour + 1 h)``: ``low``, ``high`` and ``n`` count the values archived at
those times. Rows written before Historian 0.5 have no ``n``: ``build`` computes them again.

The time-weighted mean of any span made of whole hours is then ``sum(area) / sum(cover)``,
the same number ``Reader.series`` gets from the samples (same segments, linear or held), so a
trend over a year on a grid of hours or days reads 8,760 rows per signal instead of every chunk.

Only hours that end before a point's last archived value are kept ("sealed"): later hours
still change with every flush and are always computed from the samples. The collector fills
missing hours a bounded number at a time (``build``); the archive drops the hours a write may
change (``ArchiveStore.append``, ``replace``, ``prune``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

from histcraft.archive.store import HOUR_MS, ArchiveStore

# Hours filled per point at each housekeeping (a month): a year of history fills in a day.
BUILD_HOURS = 24 * 31
# A grid this coarse or coarser, in whole hours, reads rollups.
MIN_GRID_MS = HOUR_MS
# ``(hour, cover, area, low, high, n)``; ``ArchiveStore.rollups`` gives the rest by hour.
Row = tuple[Any, ...]


def _floor(ms: int) -> int:
    return ms - ms % HOUR_MS


def hour_integrals(
    times: np.ndarray, values: np.ndarray, step: bool, edges: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Cover and area of the rebuilt signal between consecutive ``edges``."""

    from histcraft.archive.query import _cumulative, _integral_at

    if len(times) < 2:
        zeros = np.zeros(len(edges) - 1)
        return zeros, zeros.copy()
    times_f = times.astype(float)
    cover = _integral_at(times_f, values, step, 0, _cumulative(times, values, step, 0), edges)
    area = _integral_at(times_f, values, step, 1, _cumulative(times, values, step, 1), edges)
    return np.diff(cover), np.diff(area)


def hour_extremes(
    times: np.ndarray, values: np.ndarray, edges: np.ndarray
) -> tuple[list[float | None], list[float | None], list[int]]:
    """Per ``[edges[i], edges[i+1])``: the lowest and highest archived value (None without one)
    and how many there are (gaps not counted)."""

    finite = np.isfinite(values)
    times, values = times[finite], values[finite]
    cuts = np.searchsorted(times, edges, side="left")
    low: list[float | None] = []
    high: list[float | None] = []
    count: list[int] = []
    for a, b in zip(cuts[:-1].tolist(), cuts[1:].tolist(), strict=True):
        count.append(b - a)
        low.append(float(values[a:b].min()) if b > a else None)
        high.append(float(values[a:b].max()) if b > a else None)
    return low, high, count


def build(
    archive: ArchiveStore, points: Iterable[tuple[int, bool]], hours: int = BUILD_HOURS
) -> int:
    """Fill missing sealed hours of number ``points`` (``(id, step)``); hours written."""

    written = 0
    for point, step in points:
        span = archive.span(point)
        if span is None:
            continue
        # The first hour is left out: a `both` point joins its source's values there.
        first, sealed = _floor(span[0]) + HOUR_MS, _floor(span[1])
        if sealed <= first:
            continue
        known = archive.rollups(point, step, first, sealed)
        missing = [
            hour
            for hour in range(first, sealed, HOUR_MS)
            if hour not in known or known[hour][4] is None
        ][:hours]
        rows: list[Row] = []
        for start, end in _runs(missing):
            times, values = archive.read(point, start, end)
            if isinstance(values, list):
                break  # a text point: no means to keep
            edges = np.arange(start, end + 1, HOUR_MS, dtype=float)
            numbers = np.asarray(values, dtype=float)
            cover, area = hour_integrals(times, numbers, step, edges)
            low, high, count = hour_extremes(times, numbers, edges)
            rows.extend(
                (int(hour), float(c), float(a), lo, hi, n)
                for hour, c, a, lo, hi, n in zip(
                    edges[:-1], cover, area, low, high, count, strict=True
                )
            )
        if rows:
            archive.put_rollups(point, step, rows)
            written += len(rows)
    return written


def _runs(hours: list[int]) -> list[tuple[int, int]]:
    """Consecutive hours as ``[start, end)`` spans."""

    runs: list[tuple[int, int]] = []
    for hour in hours:
        if runs and runs[-1][1] == hour:
            runs[-1] = (runs[-1][0], hour + HOUR_MS)
        else:
            runs.append((hour, hour + HOUR_MS))
    return runs


def grid_extremes(
    rollups: dict[int, Row], edges: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per cell of ``edges`` (whole hours): the lowest and highest archived value from the
    rollups (NaN without one), and whether every hour of the cell had its extremes there."""

    count = len(edges) - 1
    low, high = np.full(count, np.nan), np.full(count, np.nan)
    whole = np.zeros(count, dtype=bool)
    for i in range(count):
        found = [rollups.get(hour) for hour in range(int(edges[i]), int(edges[i + 1]), HOUR_MS)]
        if not found or any(item is None or item[4] is None for item in found):
            continue
        whole[i] = True
        lows = [item[2] for item in found if item[2] is not None]
        highs = [item[3] for item in found if item[3] is not None]
        if lows:
            low[i], high[i] = min(lows), max(highs)
    return low, high, whole


def grid_means(rollups: dict[int, Row], edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per cell of ``edges`` (whole hours): the mean from rollups, and whether every hour of
    the cell was there (cells that are not must be computed from the samples)."""

    count = len(edges) - 1
    means = np.full(count, np.nan)
    whole = np.zeros(count, dtype=bool)
    for i in range(count):
        hours = range(int(edges[i]), int(edges[i + 1]), HOUR_MS)
        found: list[Any] = [rollups.get(hour) for hour in hours]
        if not found or any(item is None for item in found):
            continue
        whole[i] = True
        cover = sum(item[0] for item in found)
        if cover > 0:
            means[i] = sum(item[1] for item in found) / cover
    return means, whole
