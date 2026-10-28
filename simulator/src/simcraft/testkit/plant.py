"""The plant every server of the kit publishes: a few loops of the Simulator on a fixed grid.

The same arguments give the same series, so a check computes what it expects without asking
the server. Scenarios are off: values are good and every sample is on the grid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..engine import PlantSimulator

LOOPS = ("FIC-101", "PIC-102", "LIC-103")
ROLES = ("PV", "SP", "OP", "MODE")
START = datetime(2026, 10, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Series:
    """One tag: ``<loop>.<role>``, its unit, ``number`` or ``text``, times in ms UTC."""

    tag: str
    unit: str
    kind: str
    times: list[int] = field(default_factory=list)
    values: list[float | str] = field(default_factory=list)

    @property
    def last(self) -> float | str:
        return self.values[-1]


def history(
    *,
    start: datetime = START,
    minutes: float = 30,
    step_seconds: int = 10,
    loops: tuple[str, ...] = LOOPS,
    seed: int = 20260903,
) -> dict[str, Series]:
    """``minutes`` of the loops' PV, SP, OP and MODE, one sample every ``step_seconds``."""

    simulator = PlantSimulator(seed=seed, start_at=start, enabled_scenarios=frozenset())
    wanted = {f"Plant.ControlLoops.{loop}.{role}" for loop in loops for role in ROLES}
    found: dict[str, Series] = {}
    for _ in range(int(minutes * 60 // step_seconds)):
        frame = simulator.advance(step_seconds)
        stamp = int(frame.timestamp.timestamp() * 1000)
        for item in frame.observations:
            path = item.node_id.partition(";s=")[2]
            if path not in wanted:
                continue
            tag = path.removeprefix("Plant.ControlLoops.")
            kind = "text" if isinstance(item.value, str) else "number"
            series = found.setdefault(tag, Series(tag, item.engineering_unit, kind))
            series.times.append(stamp)
            series.values.append(item.value if kind == "text" else float(item.value))
    return dict(sorted(found.items()))


def numbers(series: dict[str, Series]) -> dict[str, Series]:
    return {tag: item for tag, item in series.items() if item.kind == "number"}
