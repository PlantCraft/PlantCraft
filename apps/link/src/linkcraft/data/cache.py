"""The raw samples Analytics read last round, kept so the next round asks only for what is new.

A round reads each signal's last 24 h every 10 to 30 minutes: 48 to 144 times the same values a
day. ``RawCache`` keeps each signal's samples of the last read with the end it was read to; the
next read of a window that starts inside them asks the Historian only from that end, minus
``overlap`` (values that arrive late, a collector's last minute settling), and keeps the rest.

What it does not see: values written into the past further back than ``overlap`` (a backfill, a
CSV import). Every ``refresh`` seconds each signal is read whole again, so such changes show up
within that time. ``LINKCRAFT_READ_CACHE=0`` turns it off (every read whole, as before 0.6).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import pandas as pd

OVERLAP_SECONDS = 900.0
REFRESH_SECONDS = 6 * 3600.0
CACHE_ENV = "LINKCRAFT_READ_CACHE"


def enabled_by_default() -> bool:
    return os.environ.get(CACHE_ENV, "1").strip() != "0"


@dataclass
class _Kept:
    values: pd.Series  # UTC index, sorted, unique
    start: pd.Timestamp  # the window it holds: [start, until]
    until: pd.Timestamp
    read_at: float  # monotonic time of the last whole read
    quality: list | None = None  # the quality changes read with them, when asked for


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
    ):
        self.overlap = pd.Timedelta(seconds=overlap_seconds)
        self.refresh = refresh_seconds
        self.clock = clock
        self._kept: dict[str, _Kept] = {}
        self._lock = threading.Lock()

    def since(self, signal: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp | None:
        """Where a read of ``[start, end]`` of ``signal`` can begin, or None: read it whole."""

        with self._lock:
            kept = self._kept.get(signal)
        if kept is None or kept.start > start or kept.until > end:
            return None
        if self.clock() - kept.read_at >= self.refresh:
            return None
        since = kept.until - self.overlap
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
                whole, read_at = values, now
            else:
                old = kept.values
                old = old[(old.index >= start) & (old.index < since)]
                whole = pd.concat([old, values]) if len(old) else values
                read_at = kept.read_at
                if quality is not None:
                    quality = joined_quality(kept.quality, quality, since)
            if quality is not None:
                whole.attrs["quality"] = quality
            self._kept[signal] = _Kept(whole, start, end, read_at, quality)
        return whole

    def drop(self, signal: str) -> None:
        with self._lock:
            self._kept.pop(signal, None)

    def values(self) -> int:
        with self._lock:
            return sum(len(kept.values) for kept in self._kept.values())

    def nbytes(self) -> int:
        with self._lock:
            return sum(
                int(kept.values.memory_usage(index=True, deep=True)) for kept in self._kept.values()
            )


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
