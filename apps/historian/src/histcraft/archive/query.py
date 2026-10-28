"""Reading the archive: recorded values, regular grids and aggregates (docs/boundary.md).

The signal is rebuilt from the archived values: straight lines between them
(numbers), or steps (step points and text). The snapshot (the newest value read,
held by the compressor) ends the signal, so reads reach the present. A "no data"
marker (NaN or ``None``) cuts the signal: nothing is rebuilt across a gap, and
the signal is unknown after its last value. A signal recorded on change (a text
signal, or a tag whose last word is ``SP``, ``SETPOINT`` or ``MODE``:
``plantcraft_sdk.contract.recorded_on_change``) is the exception on a grid: it is
rebuilt as steps and its last value holds to ``end`` or now, whichever comes first,
with no limit, as PlantCraft API v1 grids do since plantcraft-sdk 0.8.3.

Answers use the shapes of PlantCraft API v1 (``plantcraft_sdk.contract``).
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.contract import (
    AGGREGATIONS,
    MAX_POINTS,
    ContractError,
    iso,
    iso_many,
    parse_window,
    recorded_on_change,
)

from histcraft.archive import rollup
from histcraft.archive.store import HOUR_MS, ArchiveStore
from histcraft.i18n import t
from histcraft.kinds import change_kind, labelled, outward, outward_one


@dataclass(frozen=True)
class PointRef:
    """What a read needs to know about a point. ``tag`` is the name answers carry (its signal id).

    ``mode`` says where the history comes from (catalog/store.py): ``archive`` (here),
    ``source`` (read from the plant system on each request) or ``both``.
    """

    id: int
    tag: str
    kind: str = "number"
    step: bool = False
    mode: str = "archive"


class SourceUnavailable(RuntimeError):
    """The plant system a signal is read from did not answer (HTTP 502); says why."""


# Reads history from a point's source: (point, start ms, end ms) -> (times ms, values), the
# last value before start included. Raises with a readable message when the source fails.
SourceRead = Callable[[PointRef, int, int], tuple[np.ndarray, Any]]


def to_ms(moment: datetime) -> int:
    return int(moment.astimezone(timezone.utc).timestamp() * 1000)


def from_ms(values: np.ndarray) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(np.asarray(values, dtype=np.int64), unit="ms", utc=True))


# The min/max band of a trend reads every archived value: up to this many days (hours the
# rollups keep do not count).
EXTREMES_DAYS = 7
# A window's mean, min or max reads the rollups of its whole hours from this many on.
ROLLED_WINDOW_HOURS = 3


class Reader:
    def __init__(self, archive: ArchiveStore, source_read: SourceRead | None = None):
        self.archive = archive
        self.source_read = source_read

    # Raw access -------------------------------------------------------------------

    def samples(self, point: PointRef, start_ms: int, end_ms: int) -> tuple[np.ndarray, Any]:
        """The values that rebuild the signal over ``[start, end]``, by the point's mode.

        ``archive``: archived values with the snapshot appended when newer. ``source``: the
        source's recorded values. ``both``: the archive, and before its first value (a signal
        archived since last week, read for last month) the source's.
        """

        if point.mode == "source":
            return self._from_source(point, start_ms, end_ms)
        times, values = self._archived(point, start_ms, end_ms)
        if point.mode == "both" and self.source_read is not None:
            upto = self.source_gap(times, start_ms, end_ms)
            if upto is not None:
                try:
                    older = self._from_source(point, start_ms, upto)
                except Exception:  # noqa: BLE001 - the archive alone still answers
                    return times, values
                return self.with_older(point, (times, values), older)
        return times, values

    def archived(self, point: PointRef, start_ms: int, end_ms: int) -> tuple[np.ndarray, Any]:
        """The archived values with the snapshot, without the source's (``samples`` adds them)."""

        return self._archived(point, start_ms, end_ms)

    @staticmethod
    def source_gap(times: np.ndarray, start_ms: int, end_ms: int) -> int | None:
        """Where a ``both`` read needs its source: up to the first archived value, or None."""

        first = int(times[0]) if len(times) else None
        if first is not None and first <= start_ms:
            return None
        return end_ms if first is None else min(first, end_ms)

    @staticmethod
    def with_older(
        point: PointRef, archived: tuple[np.ndarray, Any], older: tuple[np.ndarray, Any]
    ) -> tuple[np.ndarray, Any]:
        """The source's values (normalized) before the first archived one, then the archive's."""

        times, values = archived
        old_times, old_values = older
        first = int(times[0]) if len(times) else None
        keep = old_times < first if first is not None else np.ones(len(old_times), bool)
        times = np.concatenate([old_times[keep], times])
        if labelled(point.kind):
            values = [v for v, k in zip(old_values, keep, strict=True) if k] + list(values)
        else:
            values = np.concatenate([np.asarray(old_values, dtype=float)[keep], values])
        return times, values

    def _from_source(self, point: PointRef, start_ms: int, end_ms: int) -> tuple[np.ndarray, Any]:
        if self.source_read is None:
            raise SourceUnavailable(t("This signal is read from its source, not reachable here."))
        return self.normalize(point, *self.source_read(point, start_ms, end_ms))

    @staticmethod
    def normalize(point: PointRef, times: Any, values: Any) -> tuple[np.ndarray, Any]:
        """Values read from a source as this point's kind: floats (NaN = gap) or labels."""

        times = np.asarray(times, dtype=np.int64)
        if point.kind == "text":
            return times, [None if v is None else str(v) for v in values]
        if labelled(point.kind):
            return times, list(values)
        return times, np.asarray([_number(v) for v in values], dtype=float)

    def archived_many(
        self, points: list[PointRef], start_ms: int, end_ms: int
    ) -> dict[int, tuple[np.ndarray, Any]]:
        """``archived`` of many points: two queries for the whole batch, not two per point."""

        ids = [point.id for point in points]
        chunks = self.archive.read_many(ids, start_ms, end_ms)
        snaps = self.archive.snapshots(ids)
        return {
            point.id: _with_snapshot(point, *chunks[point.id], snaps.get(point.id))
            for point in points
        }

    def _archived(self, point: PointRef, start_ms: int, end_ms: int) -> tuple[np.ndarray, Any]:
        times, values = self.archive.read(point.id, start_ms, end_ms)
        snap = self.archive.snapshots([point.id]).get(point.id)
        return _with_snapshot(point, times, values, snap)

    def last_time(self, point: PointRef) -> int | None:
        snap = self.archive.snapshots([point.id]).get(point.id)
        if snap and snap.get("ts") is not None:
            return int(snap["ts"])
        return None

    # Series -----------------------------------------------------------------------

    def series(
        self,
        point: PointRef,
        start: datetime,
        end: datetime,
        step: float | None,
        samples: tuple[np.ndarray, Any] | None = None,
        now: datetime | None = None,
    ) -> tuple[list[str], list[Any]]:
        """Recorded values, or time-weighted means on a ``step`` grid; ``samples`` read before.

        On a grid, a signal recorded on change holds its last value to ``end`` or ``now``
        (``_hold_on_change``). A point that is not a number gives the value in effect at the
        end of each cell, typed by its kind (``kinds.outward``)."""

        stamps, values = self._series(point, start, end, step, samples, now)
        return stamps, outward(point.kind, values)

    def _series(
        self,
        point: PointRef,
        start: datetime,
        end: datetime,
        step: float | None,
        samples: tuple[np.ndarray, Any] | None,
        now: datetime | None,
    ) -> tuple[list[str], list[Any]]:
        start_ms, end_ms = to_ms(start), to_ms(end)
        if samples is None and step is not None:
            rolled = self._rolled_series(point, start_ms, end_ms, step * 1000.0, now)
            if rolled is not None:
                return rolled
        times, values = samples if samples is not None else self.samples(point, start_ms, end_ms)
        if step is None:
            return _recorded(times, values, point.kind, start_ms, end_ms)
        on_change = recorded_on_change(point.tag, change_kind(point.kind))
        if on_change:
            until = min(end_ms, to_ms(now or datetime.now(timezone.utc)))
            times, values = _hold_on_change(times, values, point.kind, until)
        step_ms = step * 1000.0
        count = int(math.ceil((end_ms - start_ms) / step_ms))
        if count > MAX_POINTS:
            raise ContractError(
                t(
                    "Too many values: at most {count} per request. Use a larger step.",
                    count=MAX_POINTS,
                )
            )
        edges = start_ms + np.arange(count + 1, dtype=float) * step_ms
        grid = iso_ms(edges[:-1].astype(np.int64))
        if labelled(point.kind):
            return grid, _labels_at(times, values, edges[1:], edges[:-1])
        if point.kind != "number":
            held = _labels_at(times, values, edges[1:], edges[:-1])
            return grid, [None if v is None or not math.isfinite(v) else float(v) for v in held]
        means = _averages(times, values, point.step or on_change, edges)
        return grid, _json_numbers(means)

    def extremes(
        self, point: PointRef, start: datetime, end: datetime, step: float
    ) -> tuple[list[Any], list[Any]] | None:
        """The lowest and highest value read in each cell of the ``step`` grid ``series`` uses
        (the archived values: the corners the compression kept), or None past ``EXTREMES_DAYS``
        or for a point that is not a number."""

        start_ms, end_ms = to_ms(start), to_ms(end)
        if point.kind != "number" or point.mode == "source":
            return None
        step_ms = step * 1000.0
        count = int(math.ceil((end_ms - start_ms) / step_ms))
        if count > MAX_POINTS:
            return None
        edges = start_ms + np.arange(count + 1, dtype=float) * step_ms
        low, high = np.full(count, np.nan), np.full(count, np.nan)
        missing = np.arange(count)
        if self.rollups_help(point, start_ms, step):
            # Whole hours: the hourly rollups keep each hour's extremes, past EXTREMES_DAYS too.
            held = bool(point.step or recorded_on_change(point.tag, change_kind(point.kind)))
            kept = self.archive.rollups(point.id, held, start_ms, int(edges[-1]))
            low, high, whole = rollup.grid_extremes(kept, edges)
            missing = np.flatnonzero(~whole)
        if not len(missing):
            return _json_numbers(low), _json_numbers(high)
        first, last = int(missing[0]), int(missing[-1]) + 1
        span_start, span_end = int(edges[first]), min(int(edges[last]), end_ms)
        if span_end - span_start > EXTREMES_DAYS * 86_400_000:
            return None
        times, values = self.samples(point, span_start, span_end)
        numbers = np.asarray(values, dtype=float) if len(values) else np.zeros(0)
        cells = np.floor((np.asarray(times, dtype=float) - start_ms) / step_ms).astype(np.int64)
        keep = (cells >= first) & (cells < last) & ~np.isnan(numbers)
        keep &= np.isin(cells, missing)
        part_low, part_high = np.full(count, np.nan), np.full(count, np.nan)
        np.fmin.at(part_low, cells[keep], numbers[keep])
        np.fmax.at(part_high, cells[keep], numbers[keep])
        low[missing], high[missing] = part_low[missing], part_high[missing]
        return _json_numbers(low), _json_numbers(high)

    @staticmethod
    def rollups_help(point: PointRef, start_ms: int, step: float | None) -> bool:
        """Whether a grid read of ``point`` may come from the hourly rollups (whole hours)."""

        step_ms = None if step is None else step * 1000.0
        return not (
            step_ms is None
            or point.kind != "number"
            or point.mode == "source"
            or step_ms % rollup.MIN_GRID_MS
            or start_ms % rollup.MIN_GRID_MS
        )

    def _rolled_series(
        self, point: PointRef, start_ms: int, end_ms: int, step_ms: float, now: datetime | None
    ) -> tuple[list[str], list[Any]] | None:
        """A grid of whole hours from the hourly rollups, the cells they do not cover (the
        newest hours, an hour changed since) from the samples; None when no rollup helps."""

        if not self.rollups_help(point, start_ms, step_ms / 1000.0):
            return None
        on_change = recorded_on_change(point.tag, change_kind(point.kind))
        held = bool(point.step or on_change)
        count = int(math.ceil((end_ms - start_ms) / step_ms))
        if count > MAX_POINTS:
            return None  # the samples path says why
        edges = start_ms + np.arange(count + 1, dtype=float) * step_ms
        kept = self.archive.rollups(point.id, held, start_ms, int(edges[-1]))
        if not kept:
            return None
        means, whole = rollup.grid_means(kept, edges)
        missing = np.flatnonzero(~whole)
        # Consecutive cells without rollups, each read from the samples as one span.
        for run in (
            np.split(missing, np.flatnonzero(np.diff(missing) > 1) + 1) if len(missing) else []
        ):
            first, last = int(run[0]), int(run[-1]) + 1
            span_start, span_end = int(edges[first]), min(int(edges[last]), end_ms)
            times, values = self.samples(point, span_start, span_end)
            if on_change:
                until = min(end_ms, to_ms(now or datetime.now(timezone.utc)))
                times, values = _hold_on_change(times, values, point.kind, until)
            means[first:last] = _averages(times, values, held, edges[first : last + 1])
        return iso_ms(edges[:-1].astype(np.int64)), _json_numbers(means)

    # Runs (H2) -------------------------------------------------------------------

    def runs(
        self, point: PointRef, run_at: int | None = None, count: int = 1
    ) -> list[dict[str, Any]]:
        """A runs point's run at ``run_at`` (ms), else its newest ``count``, newest first, each
        ``{"run_at", "t", "v"}`` (a gap is null)."""

        return [
            {"run_at": iso_ms(np.array([at]))[0], "t": iso_ms(times), "v": _json_numbers(values)}
            for at, times, values in self.archive.runs(point.id, run_at=run_at, count=count)
        ]

    def run_list(self, point: PointRef, limit: int = 50) -> list[dict[str, Any]]:
        """A runs point's executions, newest first: ``{"run_at", "start", "end", "n"}``."""

        found = self.archive.run_list(point.id, limit)
        if not found:
            return []
        stamps = {
            key: iso_ms(np.array([item[key] for item in found], dtype=np.int64))
            for key in ("run_at", "start", "end")
        }
        return [
            {**{key: stamps[key][i] for key in stamps}, "n": item["n"]}
            for i, item in enumerate(found)
        ]

    # Aggregates -----------------------------------------------------------------

    def value(
        self, point: PointRef, agg: str, window: str | None, now: datetime | None = None
    ) -> dict[str, Any]:
        if agg not in AGGREGATIONS:
            raise ContractError(t("Invalid agg: use one of {aggs}.", aggs=", ".join(AGGREGATIONS)))
        span = parse_window(window or "1h")
        if point.kind in ("text", "structured", "instant") and agg != "last":
            raise ContractError(t("A {kind} signal has only agg=last.", kind=point.kind))
        end = now or datetime.now(timezone.utc)
        start = end - span
        start_ms, end_ms = to_ms(start), to_ms(end)
        answer: dict[str, Any] = {
            "signal": point.tag,
            "agg": agg,
            "window": window or "1h",
            "value": None,
            "at": None,
        }
        if agg in ("mean", "min", "max"):
            rolled = self._rolled_window(point, start_ms, end_ms)
            if rolled is not None:
                answer["at"] = iso(end)
                answer["value"] = rolled.get(agg)
                return answer
        times, values = self.samples(point, start_ms, end_ms)
        if agg == "last":
            inside = (times >= start_ms) & (times <= end_ms)
            for position in np.flatnonzero(inside)[::-1]:
                value = values[position]
                if value is None or (not labelled(point.kind) and not math.isfinite(value)):
                    break  # the newest value is a gap: nothing is known now
                answer["value"] = outward_one(
                    point.kind, value if labelled(point.kind) else float(value)
                )
                answer["at"] = iso(pd.Timestamp(int(times[position]), unit="ms", tz="UTC"))
                break
            return answer
        stats = _window_stats(times, values, point.step, start_ms, end_ms)
        answer["at"] = iso(end)
        if stats is not None:
            answer["value"] = stats[agg]
        return answer

    def _rolled_window(
        self, point: PointRef, start_ms: int, end_ms: int
    ) -> dict[str, float | None] | None:
        """``mean``, ``min`` and ``max`` of ``[start, end]`` from the hourly rollups of the longest
        run of whole hours they keep and the samples of the rest (before and after it): the
        same numbers ``_window_stats`` gets from every sample. None when the rollups would not
        spare much (then every sample is read).

        Inside a span the rebuilt signal never leaves the range of the values archived there,
        so the window's extremes are the hours' and the rest's, with the values the signal
        has at ``start`` and ``end``."""

        held = bool(point.step or recorded_on_change(point.tag, change_kind(point.kind)))
        first = start_ms + (-start_ms) % HOUR_MS
        last = end_ms - end_ms % HOUR_MS
        if (
            point.kind != "number"
            or point.mode != "archive"
            or held != bool(point.step)
            or last - first < ROLLED_WINDOW_HOURS * HOUR_MS
        ):
            return None
        kept = self.archive.rollups(point.id, held, first, last)
        # The longest run of hours kept with their extremes (the newest hours are not rolled
        # up yet, nor a point's first one): the rest is read from the samples.
        best, run = (first, first), first
        for hour in range(first, last + HOUR_MS, HOUR_MS):
            item = kept.get(hour) if hour < last else None
            if item is None or item[4] is None:
                if hour - run > best[1] - best[0]:
                    best = (run, hour)
                run = hour + HOUR_MS
        if best[1] - best[0] < ROLLED_WINDOW_HOURS * HOUR_MS:
            return None
        head, middle = best
        hours = [kept[hour] for hour in range(head, middle, HOUR_MS)]
        cover = sum(item[0] for item in hours)
        area = sum(item[1] for item in hours)
        picks = [item[2] for item in hours if item[2] is not None]
        picks += [item[3] for item in hours if item[3] is not None]
        for low, high, closed in ((start_ms, head, False), (middle, end_ms, True)):
            times, values = self.samples(point, low, high)
            numbers = np.asarray(values, dtype=float)
            if len(times) >= 2 and high > low:
                part = _window_integrals(times, numbers, held, low, high)
                cover += part[0]
                area += part[1]
            inside = (times >= low) & ((times <= high) if closed else (times < high))
            picks += numbers[inside & np.isfinite(numbers)].tolist()
            value = _value_at(times.astype(float), numbers, held, float(high if closed else low))
            if math.isfinite(value):
                picks.append(value)
        if cover <= 0 or not picks:
            return None  # every sample says what is known (the mean of a single value)
        return {"mean": area / cover, "min": float(min(picks)), "max": float(max(picks))}


def _window_integrals(
    times: np.ndarray, values: np.ndarray, step: bool, low: int, high: int
) -> tuple[float, float]:
    """Covered time and area of the rebuilt signal over ``[low, high]``."""

    edges = np.array([low, high], dtype=float)
    times_f = times.astype(float)
    cover = _integral_at(times_f, values, step, 0, _cumulative(times, values, step, 0), edges)
    area = _integral_at(times_f, values, step, 1, _cumulative(times, values, step, 1), edges)
    return float(np.diff(cover)[0]), float(np.diff(area)[0])


# Recorded values -------------------------------------------------------------------


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _with_snapshot(
    point: PointRef, times: np.ndarray, values: Any, snap: dict[str, Any] | None
) -> tuple[np.ndarray, Any]:
    """Archived values with the snapshot appended when it is newer (reads reach the present)."""

    if snap and snap.get("ts") is not None and (not len(times) or snap["ts"] > times[-1]):
        value = snap["value"]
        if not labelled(point.kind):
            # A text value in a number point (a MODE archived before its kind was known)
            # is a gap, never a failure of the whole read.
            value = _number(value)
        times = np.append(times, np.int64(snap["ts"]))
        values = [*values, value] if labelled(point.kind) else np.append(values, value)
    if not labelled(point.kind):
        values = np.asarray(values, dtype=float)
    return times, values


def _recorded(
    times: np.ndarray, values: Any, kind: str, start_ms: int, end_ms: int
) -> tuple[list[str], list[Any]]:
    inside = (times >= start_ms) & (times <= end_ms)
    if labelled(kind):
        keep = [i for i in np.flatnonzero(inside) if values[i] is not None]
        picked = [values[i] for i in keep]
        stamps = times[keep] if keep else np.empty(0, dtype=np.int64)
    else:
        keep_mask = inside & np.isfinite(values)
        picked = values[keep_mask].tolist()
        stamps = times[keep_mask]
    if len(picked) > MAX_POINTS:
        raise ContractError(
            t(
                "Too many recorded values: at most {count} per request. Give a step.",
                count=MAX_POINTS,
            )
        )
    return iso_ms(stamps), picked


_ISO_MEMO: dict[bytes, list[str]] = {}
_ISO_LOCK = threading.Lock()
_ISO_MEMO_POINTS = 20_000


def iso_ms(stamps: np.ndarray) -> list[str]:
    """``iso_many`` of millisecond times, without pandas for whole seconds (the usual case)."""

    stamps = np.asarray(stamps, dtype=np.int64)
    if not len(stamps) or (stamps % 1000).any():
        return iso_many(from_ms(stamps))
    # The signals of one grid read share their times: the last few grids are kept.
    key = stamps.tobytes() if len(stamps) <= _ISO_MEMO_POINTS else None
    with _ISO_LOCK:
        found = _ISO_MEMO.get(key) if key is not None else None
    if found is None:
        seconds = np.datetime_as_string((stamps // 1000).astype("datetime64[s]"), unit="s")
        found = np.char.add(seconds, "+00:00").tolist()
        if key is not None:
            with _ISO_LOCK:
                _ISO_MEMO[key] = found
                while len(_ISO_MEMO) > 16:
                    _ISO_MEMO.pop(next(iter(_ISO_MEMO)))
    return list(found)


def _hold_on_change(times: np.ndarray, values: Any, kind: str, until_ms: int):
    """The samples of a signal recorded on change with its last value repeated at
    ``until_ms``: it holds until its next sample, a null sample (a "no data" marker ends
    it), ``end`` or now. A source writes such a signal only when it changes, so the time
    since its last sample says nothing about an outage."""

    if not len(times) or int(times[-1]) >= until_ms:
        return times, values
    last = values[-1]
    if last is None or (not labelled(kind) and not math.isfinite(float(last))):
        return times, values
    times = np.append(times, np.int64(until_ms))
    if labelled(kind):
        return times, [*values, last]
    return times, np.append(np.asarray(values, dtype=float), float(last))


def _json_numbers(values: np.ndarray) -> list[float | None]:
    finite = np.isfinite(values)
    return [float(v) if ok else None for v, ok in zip(values.tolist(), finite, strict=True)]


# Rebuilt signal ----------------------------------------------------------------


def _segments(times: np.ndarray, values: np.ndarray, step: bool):
    """Per segment ``[t_i, t_i+1]``: start, end, value at both ends and whether it is known."""

    t0, t1 = times[:-1].astype(float), times[1:].astype(float)
    v0 = values[:-1]
    v1 = v0 if step else values[1:]
    valid = np.isfinite(v0) & np.isfinite(v1) & (t1 > t0)
    return t0, t1, np.where(valid, v0, 0.0), np.where(valid, v1, 0.0), valid


def _cumulative(times: np.ndarray, values: np.ndarray, step: bool, power: int):
    """Integrals at the knots of ``v**power`` (0: covered time, 1: area, 2: squares)."""

    t0, t1, v0, v1, valid = _segments(times, values, step)
    width = np.where(valid, t1 - t0, 0.0)
    if power == 0:
        part = width
    elif power == 1:
        part = width * (v0 + v1) / 2.0
    else:
        part = width * (v0 * v0 + v0 * v1 + v1 * v1) / 3.0
    return np.concatenate([[0.0], np.cumsum(part)])


def _integral_at(times, values, step, power, knots, x):
    """The integral of ``v**power`` from the first knot to each ``x``."""

    if len(times) < 2:
        return np.zeros(len(x))
    t0, t1, v0, v1, valid = _segments(times, values, step)
    index = np.clip(np.searchsorted(times, x, side="right") - 1, 0, len(times) - 2)
    before = x <= times[0]
    after = x >= times[-1]
    dx = np.clip(x - t0[index], 0.0, None)
    width = t1[index] - t0[index]
    fraction = np.divide(dx, width, out=np.zeros_like(dx), where=width > 0)
    a = v0[index]
    b = a + (v1[index] - a) * fraction  # value at x
    if power == 0:
        part = dx
    elif power == 1:
        part = dx * (a + b) / 2.0
    else:
        part = dx * (a * a + a * b + b * b) / 3.0
    part = np.where(valid[index], part, 0.0)
    out = knots[index] + part
    out = np.where(before, 0.0, out)
    return np.where(after, knots[-1], out)


def _averages(times: np.ndarray, values: np.ndarray, step: bool, edges: np.ndarray) -> np.ndarray:
    """Time-weighted average of the rebuilt signal over each ``[edges[i], edges[i+1])``."""

    if len(times) < 2:
        return np.full(len(edges) - 1, np.nan)
    times_f = times.astype(float)
    cover = _integral_at(times_f, values, step, 0, _cumulative(times, values, step, 0), edges)
    area = _integral_at(times_f, values, step, 1, _cumulative(times, values, step, 1), edges)
    covered = np.diff(cover)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(covered > 0, np.diff(area) / np.where(covered > 0, covered, 1.0), np.nan)


def _value_at(times: np.ndarray, values: np.ndarray, step: bool, x: float) -> float:
    if not len(times) or x < times[0] or x > times[-1]:
        return math.nan
    i = int(np.searchsorted(times, x, side="right") - 1)
    if i >= len(times) - 1:
        return float(values[-1]) if x == times[-1] else math.nan
    a, b = values[i], values[i + 1]
    if not math.isfinite(a):
        return math.nan
    if step:
        return float(a)
    if not math.isfinite(b):
        return float(a) if x == times[i] else math.nan
    return float(a + (b - a) * (x - times[i]) / (times[i + 1] - times[i]))


def _window_stats(times, values, step, start_ms, end_ms) -> dict[str, float | None] | None:
    if len(times) < 1:
        return None
    edges = np.array([start_ms, end_ms], dtype=float)
    times_f = times.astype(float)
    if len(times) >= 2:
        cover = np.diff(
            _integral_at(times_f, values, step, 0, _cumulative(times, values, step, 0), edges)
        )[0]
    else:
        cover = 0.0
    inside = (times >= start_ms) & (times <= end_ms) & np.isfinite(values)
    picks = list(values[inside])
    for edge in (start_ms, end_ms):
        value = _value_at(times_f, values, step, float(edge))
        if math.isfinite(value):
            picks.append(value)
    if not picks:
        return None
    if cover > 0:
        area = np.diff(
            _integral_at(times_f, values, step, 1, _cumulative(times, values, step, 1), edges)
        )[0]
        squares = np.diff(
            _integral_at(times_f, values, step, 2, _cumulative(times, values, step, 2), edges)
        )[0]
        mean = area / cover
        variance = max(squares / cover - mean * mean, 0.0)
        std = math.sqrt(variance)
    else:
        mean = float(np.mean(picks))
        std = 0.0
    return {"mean": float(mean), "min": float(min(picks)), "max": float(max(picks)), "std": std}


def _labels_at(times: np.ndarray, labels: list[Any], ends: np.ndarray, starts: np.ndarray):
    """The label in effect at the end of each interval (``None`` in a gap or after the data)."""

    if not len(times):
        return [None] * len(ends)
    found: list[Any] = []
    last = float(times[-1])
    positions = np.searchsorted(times, ends, side="left") - 1
    for position, begin in zip(positions.tolist(), starts.tolist(), strict=True):
        if position < 0 or begin > last:
            found.append(None)
        else:
            found.append(labels[position])
    return found
