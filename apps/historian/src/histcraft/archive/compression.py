"""Which values to archive: swinging-door compression, per point.

The collector feeds every value it reads to the point's ``Compressor``; the
compressor answers with the values to archive. Rebuilding the signal with
straight lines between archived values never strays more than ``deviation``
(engineering units) from any value read. This is the classic swinging-door
trending algorithm (Bristol, 1990), the method historians of this category use.

- The newest value read is held (the *snapshot*) until a later value shows it
  is needed: reads include it, so the archive always reaches the present.
- A value is archived at least every ``max_seconds`` even on a flat signal.
- ``deviation = 0`` archives every change (repeats of the same value still
  collapse into the two ends of a flat run).
- ``percent`` (a point with no known range) replaces ``deviation`` on lines: each
  segment is kept within that share of the value it starts from (0 near 0).
- **Step points** (on/off states, set points moved by hand) and **text** keep
  a value until the next one: every change is archived, with the value held
  before it, so a rebuilt step is exact.
- A gap (no value, bad quality, connection lost) archives the snapshot and a
  "no data" marker (NaN, or ``None`` for text); the next good value starts afresh.
- **Exception** (``exception``, or ``exception_percent`` of the value with no known range;
  round 8 D1, as PI does at its interfaces): before the compression, a value read within the
  exception of the last value passed on is taken as that value again, so noise smaller than
  it never reaches the compression. A line then never strays more than the exception plus the
  deviation from a value read, and a value is still passed on at least every ``max_seconds``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from histcraft.kinds import labelled

Sample = tuple[int, Any]


@dataclass
class Compressor:
    deviation: float = 0.0
    max_seconds: float = 3600.0
    kind: str = "number"
    step: bool = False
    # Deviation as a % of the archived value, for points with no known range; None: ``deviation``.
    percent: float | None = None
    # The exception before the compression (lines only): engineering units, or a % of the value.
    exception: float = 0.0
    exception_percent: float | None = None
    # Last archived (time ms, value); None before the first value or after a gap.
    archived: Sample | None = None
    # Newest value read and not archived yet.
    snapshot: Sample | None = None
    _low: float = field(default=-math.inf, repr=False)
    _high: float = field(default=math.inf, repr=False)
    _gap: bool = field(default=False, repr=False)
    # The last value the exception passed on to the compression.
    _passed: Sample | None = field(default=None, repr=False)

    @property
    def held(self) -> bool:
        """True while a step or text point holds a value that is not archived yet."""

        return self.snapshot is not None

    def feed(self, at_ms: int, value: Any, *, keep: bool = False) -> list[Sample]:
        """Take one value read at ``at_ms``; return the values to archive, oldest first.

        ``keep`` archives this value whatever the compression says (the held snapshot first):
        a change of quality starts there, so the archive holds the value where it changed.
        """

        if self.snapshot is not None and at_ms <= self.snapshot[0]:
            return []  # repeated or out-of-order read: the archive only moves forward
        if self.archived is not None and at_ms <= self.archived[0]:
            return []
        if _missing(value, self.kind):
            return self.gap(at_ms)
        value = _clean(value, self.kind)
        self._gap = False
        if keep or self.archived is None:
            self._passed = None
        if keep and self.archived is not None:
            out = [self.snapshot] if self.snapshot is not None else []
            out.append((at_ms, value))
            self.archived, self.snapshot = (at_ms, value), None
            self._reset()
            return out
        if self.archived is None:
            self.archived = (at_ms, value)
            self.snapshot = None
            self._reset()
            return [(at_ms, value)]
        if self.kind != "number" or self.step:
            return self._feed_step(at_ms, value)
        return self._feed_line(at_ms, self._excepted(at_ms, value))

    def gap(self, at_ms: int) -> list[Sample]:
        """No value at ``at_ms`` (bad quality, connection lost): close the line with a marker."""

        if self._gap:
            return []
        out: list[Sample] = []
        if self.snapshot is not None:
            out.append(self.snapshot)
        last = out[-1][0] if out else (self.archived[0] if self.archived else None)
        # The marker always follows the last value: a source clock a few ms ahead of ours
        # (or the same ms) must not swallow it.
        at_ms = at_ms if last is None else max(at_ms, last + 1)
        out.append((at_ms, None if labelled(self.kind) else math.nan))
        self.archived = None
        self.snapshot = None
        self._passed = None
        self._gap = True
        self._reset()
        return out

    def flush(self) -> list[Sample]:
        """Archive the snapshot now (on shutdown, or when a point is removed)."""

        if self.snapshot is None:
            return []
        out = [self.snapshot]
        self.archived, self.snapshot = self.snapshot, None
        self._reset()
        return out

    # Step and text ------------------------------------------------------------

    def _feed_step(self, at_ms: int, value: Any) -> list[Sample]:
        assert self.archived is not None
        held = self.snapshot[1] if self.snapshot is not None else self.archived[1]
        overdue = (at_ms - self.archived[0]) / 1000.0 >= self.max_seconds
        changed = value != held if labelled(self.kind) else abs(value - held) > self.deviation
        if changed:
            out = [self.snapshot] if self.snapshot is not None else []
            out.append((at_ms, value))
            self.archived, self.snapshot = (at_ms, value), None
            return out
        if overdue:
            self.archived, self.snapshot = (at_ms, held), None
            return [(at_ms, held)]
        self.snapshot = (at_ms, held)
        return []

    # Straight lines -------------------------------------------------------------

    def _reset(self) -> None:
        self._low, self._high = -math.inf, math.inf

    def _excepted(self, at_ms: int, value: float) -> float:
        """The value the compression takes: the last one passed on while ``value`` is within
        the exception of it (and it is not older than ``max_seconds``), else ``value``."""

        passed = self._passed or self.archived
        if passed is None:
            return value
        if self.exception_percent is not None:
            tolerance = abs(float(passed[1])) * self.exception_percent / 100.0
        else:
            tolerance = self.exception
        fresh = (at_ms - passed[0]) / 1000.0 <= self.max_seconds
        if tolerance > 0 and fresh and abs(value - float(passed[1])) <= tolerance:
            return float(passed[1])
        self._passed = (at_ms, value)
        return value

    def _feed_line(self, at_ms: int, value: float) -> list[Sample]:
        assert self.archived is not None
        out: list[Sample] = []
        overdue = (at_ms - self.archived[0]) / 1000.0 > self.max_seconds
        if self.snapshot is not None and (overdue or not self._fits(at_ms, value)):
            out.append(self.snapshot)
            self.archived = self.snapshot
            self._reset()
            if (at_ms - self.archived[0]) / 1000.0 > self.max_seconds:
                out.append((at_ms, value))
                self.archived, self.snapshot = (at_ms, value), None
                return out
        self._narrow(at_ms, value)
        self.snapshot = (at_ms, value)
        return out

    def tolerance(self) -> float:
        """The deviation of the segment being drawn: fixed, or ``percent`` of where it starts."""

        if self.percent is None or self.archived is None:
            return self.deviation
        return abs(float(self.archived[1])) * self.percent / 100.0

    def _slopes(self, at_ms: int, value: float) -> tuple[float, float]:
        t0, v0 = self.archived  # type: ignore[misc]
        span = (at_ms - t0) / 1000.0
        deviation = self.tolerance()
        return (value - deviation - v0) / span, (value + deviation - v0) / span

    def _fits(self, at_ms: int, value: float) -> bool:
        """The line from the archived value to this one passes every value read in between."""

        t0, v0 = self.archived  # type: ignore[misc]
        slope = (value - v0) / ((at_ms - t0) / 1000.0)
        return self._low - 1e-12 <= slope <= self._high + 1e-12

    def _narrow(self, at_ms: int, value: float) -> None:
        low, high = self._slopes(at_ms, value)
        self._low, self._high = max(self._low, low), min(self._high, high)

    def state(self) -> dict[str, Any]:
        return {"archived": self.archived, "snapshot": self.snapshot}


def _missing(value: Any, kind: str) -> bool:
    if value is None:
        return True
    if labelled(kind):
        return False
    try:
        return not math.isfinite(float(value))
    except (TypeError, ValueError):
        return True


def _clean(value: Any, kind: str) -> Any:
    if kind == "text":
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    if kind == "structured":
        return value
    if isinstance(value, bool):
        return float(value)
    return float(value)
