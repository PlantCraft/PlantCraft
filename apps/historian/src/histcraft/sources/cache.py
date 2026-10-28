"""A short memory of recent source reads (signals in ``source`` mode; gap G20).

Dashboards ask the same signals again every refresh, each time up to "now". Each
(source, address) keeps the values of its last read and the span they cover. A read inside the
span is answered from memory; a read past its end asks the source only for the tail (from a
little before the cached end, so late samples are picked up) and joins it on. A span is kept
for ``seconds`` after its first read, then read whole again, so a value the plant system
corrected is seen within that time. Nothing here is written to disk.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

# Each tail read starts this long before the cached end: samples reach a historian late.
LATE_MS = 5 * 60 * 1000
# Reads asked this soon after the last one, ending this close to it, need no source call.
FRESH_MS = 5 * 1000
MAX_ENTRIES = 5_000
MAX_POINTS = 200_000

Answer = tuple[np.ndarray, Any] | str
Fetch = Callable[[list[str], int, int], dict[str, Answer]]


@dataclass
class _Span:
    start_ms: int
    end_ms: int
    times: np.ndarray
    values: Any  # float64 array, or a list of text
    born: float
    read_at: float


def _slice(span: _Span, start_ms: int, end_ms: int) -> tuple[np.ndarray, Any]:
    # The values in [start, end] and the last one before start, as the source answers.
    first = max(int(np.searchsorted(span.times, start_ms, side="left")) - 1, 0)
    last = int(np.searchsorted(span.times, end_ms, side="right"))
    return span.times[first:last].copy(), span.values[first:last]


def _join(head: _Span, cut_ms: int, tail: tuple[np.ndarray, Any]) -> tuple[np.ndarray, Any] | None:
    times, values = tail
    if isinstance(values, list) != isinstance(head.values, list):
        return None  # a number became text (or back): read it whole again
    keep = head.times < cut_ms
    fresh = times >= cut_ms
    joined = np.concatenate([head.times[keep], times[fresh]])
    if isinstance(values, list):
        kept = [value for value, ok in zip(head.values, keep, strict=True) if ok]
        return joined, kept + [value for value, ok in zip(values, fresh, strict=True) if ok]
    return joined, np.concatenate([head.values[keep], values[fresh]])


class RecentReads:
    """Recent values per (source, address), shared by every request of one server."""

    def __init__(self, seconds: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self.seconds = float(seconds)
        self.clock = clock
        self._spans: OrderedDict[tuple, _Span] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.source_calls = 0

    def recorded(
        self, key: tuple, addresses: list[str], start_ms: int, end_ms: int, fetch: Fetch
    ) -> dict[str, Answer]:
        """Per address, what ``fetch(addresses, start, end)`` would answer, asking it only for
        what memory lacks. ``key`` names the source as it is now (its id and last change)."""

        if self.seconds <= 0:
            return fetch(addresses, start_ms, end_ms)
        now = self.clock()
        out: dict[str, Answer] = {}
        # Addresses grouped by the window the source must be asked for.
        asks: dict[tuple[int, int, bool], list[str]] = {}
        with self._lock:
            for address in addresses:
                span = self._spans.get((key, address))
                if span is not None and (
                    now - span.born > self.seconds or start_ms < span.start_ms
                ):
                    span = None
                if span is None:
                    asks.setdefault((start_ms, end_ms, False), []).append(address)
                elif end_ms <= span.end_ms or (
                    end_ms - span.end_ms <= FRESH_MS and (now - span.read_at) * 1000 <= FRESH_MS
                ):
                    out[address] = _slice(span, start_ms, min(end_ms, span.end_ms))
                    self._spans.move_to_end((key, address))
                    self.hits += 1
                else:
                    tail_from = max(span.start_ms, span.end_ms - LATE_MS)
                    asks.setdefault((tail_from, end_ms, True), []).append(address)
        for (ask_start, ask_end, tail), members in asks.items():
            self.source_calls += 1
            answers = fetch(members, ask_start, ask_end)
            with self._lock:
                for address in members:
                    answer = answers.get(address)
                    if answer is None or isinstance(answer, str):
                        out[address] = answer  # errors are never kept
                        continue
                    span = self._remember(key, address, ask_start, ask_end, answer, now, tail)
                    out[address] = _slice(span, start_ms, end_ms) if span else answer
        return out

    def _remember(
        self,
        key: tuple,
        address: str,
        start_ms: int,
        end_ms: int,
        answer: Any,
        now: float,
        tail: bool,
    ) -> _Span | None:
        old = self._spans.get((key, address))
        times, values = answer
        if tail and old is not None:
            joined = _join(old, start_ms, answer)
            if joined is None:
                self._spans.pop((key, address), None)
                return None
            times, values = joined
            span = _Span(old.start_ms, end_ms, times, values, old.born, now)
        else:
            span = _Span(start_ms, end_ms, np.asarray(times), values, now, now)
        if len(span.times) > MAX_POINTS:
            self._spans.pop((key, address), None)
            return None
        self._spans[(key, address)] = span
        self._spans.move_to_end((key, address))
        while len(self._spans) > MAX_ENTRIES:
            self._spans.popitem(last=False)
        return span
