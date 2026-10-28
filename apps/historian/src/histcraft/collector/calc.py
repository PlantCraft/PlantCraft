"""Calculated points: the collector's reader of the ``calc`` source.

Each point's address is a formula (``catalog.expressions``) over other points the collector
archives. On the point's scan the formula takes each input's latest value as the collector
read it, so a calculated point is never older than its inputs' last scan (a calculated point
reading another is one scan behind it). The result goes through the same compression as any
read value.

Quality, with care for sources that report none (they count as good): any input bad, missing
or disconnected makes the result bad, a gap in the archive; any input uncertain or substituted
makes it uncertain.

A totalizer (``total(...)``) integrates its formula over time (trapezoids between scans) and
restarts at each reset. It never bridges a gap: time while an input was bad adds nothing.
After a restart of the collector it continues from its last archived value when that is in
the same reset period.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from histcraft.archive.store import now_ms
from histcraft.catalog.expressions import Formula, FormulaError, parse
from histcraft.collector.reading import Reading
from histcraft.i18n import t

if TYPE_CHECKING:
    from histcraft.collector.service import Collector, PointState

# Input states that give no value to calculate with.
_NO_VALUE = ("bad", "disconnected", "waiting", "disabled")
_DOUBTFUL = ("uncertain", "substituted")


@dataclass
class Total:
    """A totalizer's running state: its reset period, the total, the last input value."""

    period: int
    value: float
    last: tuple[int, float] | None = None


def period_start(at_ms: int, reset: str) -> int:
    """The start (ms, UTC) of the reset period holding ``at_ms``; 0 when it never resets."""

    if reset == "none":
        return 0
    moment = datetime.fromtimestamp(at_ms / 1000, tz=timezone.utc)
    if reset == "hour":
        moment = moment.replace(minute=0, second=0, microsecond=0)
    elif reset == "day":
        moment = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        moment = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(moment.timestamp() * 1000)


def accumulate(total: Total, formula: Formula, at_ms: int, rate: float) -> float:
    """Add the formula's value ``rate`` at ``at_ms`` to a totalizer; its new value."""

    start = period_start(at_ms, formula.reset)
    if start != total.period:
        total.period, total.value = start, 0.0
        if total.last is not None and total.last[0] < start:
            # The part of the last step inside the new period.
            total.last = (start, total.last[1])
    if total.last is not None and at_ms > total.last[0]:
        seconds = (at_ms - total.last[0]) / 1000
        total.value += (total.last[1] + rate) / 2 * seconds / float(formula.per_seconds or 1.0)
    total.last = (at_ms, rate)
    return total.value


class CalcReader:
    """Evaluates calculated points from the values the collector holds (no connection)."""

    def __init__(self, collector: Collector):
        self.collector = collector
        self._formulas: dict[str, Formula | FormulaError] = {}
        self._by_signal: dict[str, PointState] = {}
        self._version = -2

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def test(self) -> dict[str, Any]:
        return {"points": len(self.collector.calculated())}

    async def browse(self, root: str | None = None) -> dict[str, Any]:
        return {"variables": [], "truncated": False, "limit": 0}

    def formula(self, address: str) -> Formula | FormulaError:
        if address not in self._formulas:
            try:
                self._formulas[address] = parse(address)
            except FormulaError as exc:
                self._formulas[address] = exc
        return self._formulas[address]

    async def read(self, addresses: list[str]) -> dict[str, Reading]:
        at = now_ms()
        collector = self.collector
        with collector._lock:
            if self._version != collector._version:
                self._version = collector._version
                self._by_signal = {s.point["signal"]: s for s in collector.points.values()}
            return {address: self._evaluate(address, at) for address in addresses}

    def _evaluate(self, address: str, at: int) -> Reading:
        formula = self.formula(address)
        if isinstance(formula, FormulaError):
            return Reading(at, None, False, str(formula), "bad")
        values: list[float] = []
        quality = "good"
        for signal in formula.signals:
            state = self._by_signal.get(signal)
            if state is None:
                return self._gap(address, at, t("{signal} is not collected.", signal=signal))
            if state.status in _NO_VALUE or state.last is None:
                return self._gap(address, at, t("{signal} has no value now.", signal=signal))
            value = _number(state.last[1])
            if value is None:
                return self._gap(address, at, t("{signal} is not a number.", signal=signal))
            if state.status in _DOUBTFUL:
                quality = "uncertain"
            values.append(value)
        result = formula.evaluate(values)
        if math.isnan(result):
            return self._gap(address, at, t("The formula has no value for these inputs."))
        if formula.total:
            result = accumulate(self._total(address, formula, at), formula, at, result)
        detail = t("An input is uncertain.") if quality != "good" else ""
        return Reading(at, result, True, detail, quality)

    def _gap(self, address: str, at: int, detail: str) -> Reading:
        total = self.collector.totals.get(address)
        if total is not None:
            total.last = None  # time without a value adds nothing to the total
        return Reading(at, None, False, detail, "bad")

    def _total(self, address: str, formula: Formula, at: int) -> Total:
        """A totalizer's state, kept by the collector; after a restart its archived value."""

        totals = self.collector.totals
        if address not in totals:
            start = period_start(at, formula.reset)
            totals[address] = Total(start, self._archived(address, start))
        return totals[address]

    def _archived(self, address: str, since: int) -> float:
        point = next(
            (
                state.id
                for state in self._by_signal.values()
                if state.point["source_kind"] == "calc" and state.point["address"] == address
            ),
            None,
        )
        if point is None:
            return 0.0
        snapshot = self.collector.archive.snapshots([point]).get(point) or {}
        value = _number(snapshot.get("value"))
        stamp = snapshot.get("ts")
        if value is None or stamp is None or int(stamp) < since:
            return 0.0
        return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
