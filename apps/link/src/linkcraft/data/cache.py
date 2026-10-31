"""The raw samples Analytics read last round, kept so the next round asks only for what is new.

A round reads each signal's last 24 h every 10 to 30 minutes: 48 to 144 times the same values a
day. ``RawCache`` keeps each signal's samples of the last read with the end it was read to; the
next read of a window that starts inside them asks the Historian only from that end, minus
``overlap`` (values that arrive late, a collector's last minute settling), and keeps the rest.

What it does not see: values written into the past further back than ``overlap`` (a backfill, a
CSV import). Every ``refresh`` seconds each signal is read whole again, so such changes show up
within that time. ``LINKCRAFT_READ_CACHE=0`` turns it off (every read whole, as before 0.6).

Memory: samples are kept compact when that loses nothing (times as int32 milliseconds from the
window's start, numbers as float32 when every value is one: what a PLC's REAL gives), 8 bytes a
sample instead of 16, and the cache holds at most ``LINKCRAFT_READ_CACHE_MB`` (512 MB by default):
past it, the signals used least recently are dropped and read whole next time.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
import pandas as pd

OVERLAP_SECONDS = 900.0
REFRESH_SECONDS = 6 * 3600.0
CACHE_ENV = "LINKCRAFT_READ_CACHE"
CACHE_MB_ENV = "LINKCRAFT_READ_CACHE_MB"
DEFAULT_MB = 512.0
_MS = 1_000_000  # nanoseconds in a millisecond
_INT32 = 2**31 - 1
_PER_MS = {"ms": 1, "us": 1000, "ns": _MS}


def enabled_by_default() -> bool:
    return os.environ.get(CACHE_ENV, "1").strip() != "0"


def max_bytes_by_default() -> int:
    try:
        megabytes = float(os.environ.get(CACHE_MB_ENV, DEFAULT_MB))
    except ValueError:
        megabytes = DEFAULT_MB
    return int(max(0.0, megabytes) * 1024 * 1024)


class _Packed:
    """A series kept compact when that is exact: times as int32 ms from ``base`` (ns), numbers
    as float32 when each one is a float32; otherwise the series as it is."""

    __slots__ = ("base", "offsets", "numbers", "series", "name", "attrs", "unit", "freq", "nbytes")

    def __init__(self, values: pd.Series, base: int | None = None):
        self.series: pd.Series | None = None
        self.offsets = self.numbers = None
        self.name, self.attrs = values.name, dict(values.attrs)
        index = values.index
        self.unit = getattr(index, "unit", "ns")
        self.freq = getattr(index, "freq", None)
        per = _PER_MS.get(self.unit)  # the index's units in a millisecond
        if (
            per is not None
            and isinstance(index, pd.DatetimeIndex)
            and str(index.tz) == "UTC"
            and values.dtype == np.float64
            and len(values)
        ):
            stamps = index.asi8  # in the index's own unit: no conversion
            first = int(stamps[0]) if base is None else base // (_MS // per)
            delta = stamps - first
            if (
                (per == 1 or not (delta % per).any())
                and int(delta[0]) >= 0
                and int(delta[-1]) // per <= _INT32
            ):
                numbers = values.to_numpy()
                small = numbers.astype(np.float32)
                exact = np.array_equal(small.astype(np.float64), numbers, equal_nan=True)
                self.base = first * (_MS // per)
                self.offsets = (delta // per).astype(np.int32)
                self.numbers = small if exact else numbers
                self.nbytes = int(self.offsets.nbytes + self.numbers.nbytes)
                return
        self.base = 0
        self.series = values
        self.nbytes = int(values.memory_usage(index=True, deep=values.dtype == object))

    def joined(self, start: pd.Timestamp, since: pd.Timestamp, new: _Packed) -> _Packed | None:
        """This one's samples in ``[start, since)`` followed by ``new`` (packed from the same
        ``base``), without going through pandas; None when either is not packed."""

        if self.series is not None or new.series is not None or new.unit != self.unit:
            return None
        if new.base != self.base:
            return None
        lo = -((self.base - start.value) // _MS)  # ceil((start - base) / 1 ms)
        hi = -((self.base - since.value) // _MS)
        first, last = np.searchsorted(self.offsets, [lo, hi], side="left")
        out = object.__new__(_Packed)
        out.series, out.base, out.unit, out.freq = None, self.base, self.unit, None
        out.name, out.attrs = new.name, new.attrs
        out.offsets = np.concatenate([self.offsets[first:last], new.offsets])
        mixed = self.numbers.dtype != new.numbers.dtype
        out.numbers = np.concatenate(
            [self.numbers[first:last], new.numbers], dtype=np.float64 if mixed else None
        )
        out.nbytes = int(out.offsets.nbytes + out.numbers.nbytes)
        return out

    def get(self) -> pd.Series:
        if self.series is not None:
            return self.series
        per = _PER_MS[self.unit]
        stamps = self.offsets.astype(np.int64) * per + self.base // (_MS // per)
        index = pd.DatetimeIndex(
            stamps.view(f"datetime64[{self.unit}]"), dtype=pd.DatetimeTZDtype(self.unit, "UTC")
        )
        if self.freq is not None:
            index.freq = self.freq
        out = pd.Series(self.numbers.astype(np.float64), index=index, name=self.name, copy=False)
        out.attrs.update(self.attrs)
        return out


@dataclass
class _Kept:
    packed: _Packed  # UTC index, sorted, unique
    start: pd.Timestamp  # the window it holds: [start, until]
    until: pd.Timestamp
    read_at: float  # monotonic time of the last whole read
    quality: list | None = None  # the quality changes read with them, when asked for

    @property
    def values(self) -> pd.Series:
        return self.packed.get()


def _at(change: dict) -> pd.Timestamp:
    stamp = pd.Timestamp(change["t"])
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def joined_quality(old: list | None, new: list, since: pd.Timestamp) -> list:
    """The quality changes kept before ``since`` and the ones read from it (each change holds
    until the next one; the new read's first may restate the state at ``since``)."""

    keep = [item for item in old or [] if _at(item) < since]
    if not keep:
        return list(new)
    return keep + [item for item in new if _at(item) >= since]


class RawCache:
    """Per signal: samples of ``[start, until]`` read before (thread-safe)."""

    def __init__(
        self,
        *,
        overlap_seconds: float = OVERLAP_SECONDS,
        refresh_seconds: float = REFRESH_SECONDS,
        clock=time.monotonic,
        max_bytes: int | None = None,
    ):
        self.overlap = pd.Timedelta(seconds=overlap_seconds)
        self.refresh = refresh_seconds
        self.clock = clock
        self.max_bytes = max_bytes_by_default() if max_bytes is None else max_bytes
        # Least recently used first: the order evictions follow.
        self._kept: OrderedDict[str, _Kept] = OrderedDict()
        self._bytes = 0
        self.evicted = 0
        self._lock = threading.Lock()

    def since(
        self, signal: str, start: pd.Timestamp, end: pd.Timestamp, grid: float | None = None
    ) -> pd.Timestamp | None:
        """Where a read of ``[start, end]`` of ``signal`` can begin, or None: read it whole.

        ``grid``: means over ``grid`` seconds from ``start`` are kept; the read begins on that
        grid, and only when the kept means lie on it too."""

        with self._lock:
            kept = self._kept.get(signal)
            if kept is not None:
                self._kept.move_to_end(signal)
        if kept is None or kept.start > start or kept.until > end:
            return None
        if self.clock() - kept.read_at >= self.refresh:
            return None
        since = kept.until - self.overlap
        if grid:
            cell = int(round(grid * 1e9))
            if cell <= 0 or (start.value - kept.start.value) % cell:
                return None
            since = start + pd.Timedelta((since.value - start.value) // cell * cell, unit="ns")
        return start if since <= start else since

    def merge(
        self,
        signal: str,
        values: pd.Series,
        start: pd.Timestamp,
        end: pd.Timestamp,
        since: pd.Timestamp | None,
    ) -> pd.Series:
        """``values`` read for ``[since or start, end]`` joined to what is kept, as ``[start,
        end]``; kept for the next read."""

        now = self.clock()
        quality = values.attrs.get("quality")
        with self._lock:
            kept = self._kept.get(signal)
            if since is None or kept is None:
                if quality is not None:
                    values.attrs["quality"] = quality
                packed, whole, read_at = _Packed(values), values, now
            else:
                read_at = kept.read_at
                if quality is not None:
                    quality = joined_quality(kept.quality, quality, since)
                    values.attrs["quality"] = quality
                packed = kept.packed.joined(start, since, _Packed(values, kept.packed.base))
                if packed is None:  # not packable: through pandas
                    old = kept.values
                    old = old[(old.index >= start) & (old.index < since)]
                    whole = pd.concat([old, values]) if len(old) else values
                    whole.attrs = dict(values.attrs)
                    packed = _Packed(whole)
                else:
                    whole = None
            self._put(signal, _Kept(packed, start, end, read_at, quality))
        return packed.get() if whole is None else whole

    def _put(self, signal: str, kept: _Kept) -> None:
        """Keep ``kept`` (lock held), then drop the least recently used past ``max_bytes``."""

        old = self._kept.pop(signal, None)
        if old is not None:
            self._bytes -= old.packed.nbytes
        if kept.packed.nbytes > self.max_bytes:
            return  # larger than the whole cache: read whole every time
        self._kept[signal] = kept
        self._bytes += kept.packed.nbytes
        while self._bytes > self.max_bytes and self._kept:
            _, gone = self._kept.popitem(last=False)
            self._bytes -= gone.packed.nbytes
            self.evicted += 1

    def drop(self, signal: str) -> None:
        with self._lock:
            old = self._kept.pop(signal, None)
            if old is not None:
                self._bytes -= old.packed.nbytes

    def values(self) -> int:
        with self._lock:
            return sum(
                len(kept.packed.offsets if kept.packed.series is None else kept.packed.series)
                for kept in self._kept.values()
            )

    def nbytes(self) -> int:
        """Bytes of samples kept (times and values)."""

        with self._lock:
            return self._bytes


def read_incremental(
    cache: RawCache, names: list[str], start: pd.Timestamp, end: pd.Timestamp, read
):
    """``read(names, begin, end) -> (columns, errors)`` (naive UTC times, columns with a UTC
    index) through ``cache``: signals kept from the last read are asked only from where it ended
    (minus the overlap). A column whose ``attrs["means"]`` is set (read as means) is never kept."""

    start_u, end_u = start.tz_localize("UTC"), end.tz_localize("UTC")
    groups: dict[pd.Timestamp | None, list[str]] = {}
    for name in names:
        groups.setdefault(cache.since(name, start_u, end_u), []).append(name)
    columns: dict[str, pd.Series] = {}
    errors: list = []
    for since, group in groups.items():
        begin = start if since is None else since.tz_localize(None)
        part, failed = read(group, begin, end)
        errors.extend(failed)
        for item in failed:
            cache.drop(item["signal"])
        for name, values in part.items():
            if values.attrs.get("means"):
                cache.drop(name)
                columns[name] = values
            else:
                columns[name] = cache.merge(name, values, start_u, end_u, since)
    return columns, errors


def read_means_incremental(
    cache: RawCache,
    names: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: float,
    read,
):
    """Means over ``step`` seconds through ``cache`` (what a scheduled method reads):
    ``read(names, begin, end, step) -> (columns, errors)``, UTC times, means on a grid that
    starts at ``begin``. A signal kept from a run whose grid lines up with this one (the window
    ends on a whole step) is asked only from the step where that run ended, minus the overlap;
    the means before it are the ones kept. Kept as ``signal@<step>s``, next to the raw samples
    of the loops' rounds, under the same memory limit."""

    start_u = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end_u = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")

    def key(name: str) -> str:
        return f"{name}@{step:g}s"

    groups: dict[pd.Timestamp | None, list[str]] = {}
    for name in names:
        groups.setdefault(cache.since(key(name), start_u, end_u, grid=step), []).append(name)
    columns: dict[str, pd.Series] = {}
    errors: list = []
    for since, group in groups.items():
        part, failed = read(group, start_u if since is None else since, end_u, step)
        errors.extend(failed)
        for item in failed:
            cache.drop(key(item["signal"]))
        for name, values in part.items():
            index = values.index
            if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
                cache.drop(key(name))
                columns[name] = values
                continue
            columns[name] = cache.merge(key(name), values, start_u, end_u, since)
    return columns, errors
