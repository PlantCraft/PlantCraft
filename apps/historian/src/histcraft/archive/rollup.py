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
from datetime import datetime, timezone
from typing import Any

import numpy as np

from histcraft.archive.store import HOUR_MS, ArchiveStore

# Hours filled per point at each housekeeping (a month): a year of history fills in a day.
BUILD_HOURS = 24 * 31
# A grid this coarse or coarser, in whole hours, reads rollups.
MIN_GRID_MS = HOUR_MS
DAY_MS = 24 * HOUR_MS
# Levels of ``rollups_coarse`` (H9), and how many days and months a housekeeping sums per point.
DAY, MONTH = 1, 2
BUILD_DAYS = 400
BUILD_MONTHS = 24
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
        absent = [
            hour
            for hour in range(first, sealed, HOUR_MS)
            if hour not in known or known[hour][4] is None
        ]
        missing = absent[:hours]
        # Days and months are summed only up to the first hour still missing.
        frontier = absent[hours] if len(absent) > hours else sealed
        rows: list[Row] = []
        text = False
        for start, end in _runs(missing):
            times, values = archive.read(point, start, end)
            if isinstance(values, list):
                text = True
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
        if not text:
            build_coarse(archive, point, step, frontier)
    return written


def day_floor(ms: int) -> int:
    return ms - ms % DAY_MS


def month_floor(ms: int) -> int:
    moment = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return int(datetime(moment.year, moment.month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def next_month(ms: int) -> int:
    moment = datetime.fromtimestamp(month_floor(ms) / 1000, tz=timezone.utc)
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _sum(rows: list[tuple[Any, ...]], t0: int, t1: int) -> tuple[Any, ...]:
    """``rows`` of ``(cover, area, low, high, n)`` as one ``(t0, t1, cover, area, low, high, n)``."""

    lows = [row[2] for row in rows if row[2] is not None]
    highs = [row[3] for row in rows if row[3] is not None]
    return (
        t0,
        t1,
        float(sum(row[0] for row in rows)),
        float(sum(row[1] for row in rows)),
        min(lows) if lows else None,
        max(highs) if highs else None,
        int(sum(row[4] or 0 for row in rows)),
    )


def build_coarse(archive: ArchiveStore, point: int, step: bool, frontier: int) -> tuple[int, int]:
    """Sum the hourly rows of each closed day before ``frontier`` (the first hour not rolled up
    yet) into a daily row, and the daily rows of each closed month into a monthly one (H9).

    Days go on from the newest one kept (a write in the past drops every day and month after
    it, ``ArchiveStore.append``), at most ``BUILD_DAYS`` a call; a day without data is kept with
    nothing in it, so the months that hold it close. Days and months written."""

    days_written = months_written = 0
    end_day = day_floor(frontier)
    start = archive.coarse_end(point, step, DAY)
    if start is None:
        first = archive.first_rollup(point, step)
        if first is None:
            return 0, 0
        start = day_floor(first)
    stop = min(end_day, start + BUILD_DAYS * DAY_MS)
    if stop > start:
        hours = archive.rollups(point, step, start, stop)
        days = []
        leading = archive.coarse_end(point, step, DAY) is None
        for day in range(start, stop, DAY_MS):
            found = [hours.get(h) for h in range(day, day + DAY_MS, HOUR_MS)]
            if any(item is None or item[4] is None for item in found):
                if leading and not days:
                    continue  # the first day of the history, without its first hours
                break  # an hour not rolled up yet, or kept before Historian 0.5
            days.append(_sum(found, day, day + DAY_MS))  # type: ignore[arg-type]
        if days:
            archive.put_coarse(point, step, DAY, days)
            days_written = len(days)
    last_day = archive.coarse_end(point, step, DAY)
    if last_day is None:
        return days_written, 0
    month = archive.coarse_end(point, step, MONTH)
    if month is None:
        first_day = min(archive.coarse(point, step, DAY, -(2**62), last_day), default=None)
        if first_day is None:
            return days_written, 0
        month = month_floor(first_day)
    months = []
    leading = archive.coarse_end(point, step, MONTH) is None
    while next_month(month) <= last_day and len(months) < BUILD_MONTHS:
        end = next_month(month)
        found = archive.coarse(point, step, DAY, month, end)
        if len(found) < (end - month) // DAY_MS:
            if leading and not months:
                month = end
                continue  # the first month of the history, without its first days
            break
        months.append(_sum([item[1:] for item in found.values()], month, end))
        month = end
    if months:
        archive.put_coarse(point, step, MONTH, months)
        months_written = len(months)
    return days_written, months_written


def _runs(hours: list[int]) -> list[tuple[int, int]]:
    """Consecutive hours as ``[start, end)`` spans."""

    runs: list[tuple[int, int]] = []
    for hour in hours:
        if runs and runs[-1][1] == hour:
            runs[-1] = (runs[-1][0], hour + HOUR_MS)
        else:
            runs.append((hour, hour + HOUR_MS))
    return runs


class Kept:
    """The rollups of a span as ``(t1, cover, area, low, high, n)`` rows by their start, in
    three levels (H9): months, days and hours. ``pick`` takes the coarsest row starting at a
    time that ends by a limit, so a year on a grid of days reads 365 daily rows, not 8,760
    hourly ones."""

    def __init__(self, months: dict[int, Row], days: dict[int, Row], hours: dict[int, Row]):
        self.levels = (months, days, hours)

    @classmethod
    def from_hours(cls, rollups: dict[int, Row]) -> Kept:
        return cls({}, {}, {hour: (hour + HOUR_MS, *row) for hour, row in rollups.items()})

    def __bool__(self) -> bool:
        return any(self.levels)

    def pick(self, at: int, limit: int) -> Row | None:
        for level in self.levels:
            row = level.get(at)
            if row is not None and row[0] <= limit:
                return row
        return None

    def tile(self, low: int, high: int) -> list[Row] | None:
        """The rows that cover ``[low, high)`` end to end, or None when one is missing."""

        rows: list[Row] = []
        at = low
        while at < high:
            row = self.pick(at, high)
            if row is None:
                return None
            rows.append(row)
            at = int(row[0])
        return rows if at == high else None


def kept(
    archive: ArchiveStore, point: int, step: bool, start: int, end: int, coarse: bool = True
) -> Kept:
    """The rollups of ``[start, end)``: the days and months inside it when ``coarse`` (a span
    whose reads start on whole days), and the hours outside the days kept."""

    if not coarse:
        return Kept.from_hours(archive.rollups(point, step, start, end))
    days = {t0: r for t0, r in archive.coarse(point, step, DAY, start, end).items() if r[0] <= end}
    months = {
        t0: r for t0, r in archive.coarse(point, step, MONTH, start, end).items() if r[0] <= end
    }
    if not days:
        return Kept.from_hours(archive.rollups(point, step, start, end))
    first, last = min(days), max(row[0] for row in days.values())
    hours = archive.rollups(point, step, start, first)
    hours.update(archive.rollups(point, step, last, end))
    return Kept(months, days, Kept.from_hours(hours).levels[2])


def longest_run(rows: Kept, first: int, last: int) -> tuple[int, int, list[Row]]:
    """The longest run of rows kept with their extremes inside ``[first, last)`` (hours apart):
    its start, its end and its rows (the newest hours are not rolled up yet, nor a point's
    first one)."""

    best: tuple[int, int, list[Row]] = (first, first, [])
    run_start, run, at = first, [], first
    while at < last:
        row = rows.pick(at, last)
        if row is None or row[5] is None:
            if at - run_start > best[1] - best[0]:
                best = (run_start, at, run)
            at += HOUR_MS
            run_start, run = at, []
            continue
        run.append(row)
        at = int(row[0])
    if at - run_start > best[1] - best[0]:
        best = (run_start, at, run)
    return best


def _as_kept(rollups: dict[int, Row] | Kept) -> Kept:
    return rollups if isinstance(rollups, Kept) else Kept.from_hours(rollups)


def grid_extremes(
    rollups: dict[int, Row] | Kept, edges: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per cell of ``edges`` (whole hours): the lowest and highest archived value from the
    rollups (NaN without one), and whether the whole cell had its extremes there."""

    rows_kept = _as_kept(rollups)
    count = len(edges) - 1
    low, high = np.full(count, np.nan), np.full(count, np.nan)
    whole = np.zeros(count, dtype=bool)
    for i in range(count):
        found = rows_kept.tile(int(edges[i]), int(edges[i + 1]))
        if not found or any(item[5] is None for item in found):
            continue
        whole[i] = True
        lows = [item[3] for item in found if item[3] is not None]
        highs = [item[4] for item in found if item[4] is not None]
        if lows:
            low[i], high[i] = min(lows), max(highs)
    return low, high, whole


def grid_means(rollups: dict[int, Row] | Kept, edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per cell of ``edges`` (whole hours): the mean from rollups, and whether the whole cell
    was there (cells that are not must be computed from the samples)."""

    rows_kept = _as_kept(rollups)
    count = len(edges) - 1
    means = np.full(count, np.nan)
    whole = np.zeros(count, dtype=bool)
    for i in range(count):
        found = rows_kept.tile(int(edges[i]), int(edges[i + 1]))
        if not found:
            continue
        whole[i] = True
        cover = sum(item[1] for item in found)
        if cover > 0:
            means[i] = sum(item[2] for item in found) / cover
    return means, whole
