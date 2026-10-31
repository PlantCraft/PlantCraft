"""Load limits of the suite's watch: CPU, memory and errors logged, held for some minutes.

Each tick the watch compares, for every service and for the machine:

- CPU as a share of the CPUs it may use (``cpu_load_pct``, :mod:`plantcraft.apps.host_usage`),
- memory as a share of its limit (``mem_pct``; the machine's memory in use for the machine),
- errors logged per minute (what the recorder measured on ``GET /api/ops/metrics``),

with two levels, a **warning** and a **critical** one (defaults 80 % and 95 %, 2 and 5 errors a
minute, like the defaults industrial gateways ship with). A level is an incident only once it
held ``minutes`` in a row (5 by default), so a run that peaks for a minute says nothing; it ends
when the value is back 5 points under the level (hysteresis), so a value hovering on the limit
does not open and close it every tick. An administrator changes the levels in Operations ›
Load alerts (``GET``/``PUT /api/operations/limits``); they are kept in the watch's own state.
See docs/operations.md, section 4.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from typing import Any

from plantcraft.i18n import t

# Check keys: one incident per subject and level (``WATCH_EVENTS`` names their events).
LOAD = "load"
LOAD_CRITICAL = "load_critical"
ERRORS = "errors"
ERRORS_CRITICAL = "errors_critical"
PREFIXES = (f"{LOAD}:", f"{LOAD_CRITICAL}:", f"{ERRORS}:", f"{ERRORS_CRITICAL}:")
HOST = "host"
# Back under the level by this much ends an incident (percentage points; errors: a fifth).
HYSTERESIS_PCT = 5.0


@dataclass(frozen=True)
class LoadLimits:
    enabled: bool = True
    cpu_warning: float = 80.0
    cpu_critical: float = 95.0
    memory_warning: float = 80.0
    memory_critical: float = 95.0
    errors_warning: float = 2.0
    errors_critical: float = 5.0
    minutes: int = 5

    @classmethod
    def from_dict(cls, value: Any) -> LoadLimits:
        """The limits a dict names over the defaults; unknown or malformed entries are left out."""

        base = asdict(cls())
        if isinstance(value, dict):
            for item in fields(cls):
                given = value.get(item.name)
                if item.name == "enabled":
                    if isinstance(given, bool):
                        base["enabled"] = given
                elif isinstance(given, (int, float)) and not isinstance(given, bool):
                    base[item.name] = int(given) if item.name == "minutes" else float(given)
        return cls(**base)

    def validated(self) -> LoadLimits:
        """Raises ``ValueError`` (a sentence for the person) when the limits make no sense."""

        for name in ("cpu", "memory"):
            warning, critical = getattr(self, f"{name}_warning"), getattr(self, f"{name}_critical")
            if not (10 <= warning <= 100 and 10 <= critical <= 100):
                raise ValueError(t("Percentages go from 10 to 100."))
            if critical < warning:
                raise ValueError(t("The critical level cannot be below the warning level."))
        if not (0 < self.errors_warning <= self.errors_critical <= 10_000):
            raise ValueError(
                t("Errors a minute: the warning is above 0 and not above the critical level.")
            )
        if not 1 <= self.minutes <= 120:
            raise ValueError(t("The time held goes from 1 to 120 minutes."))
        return self

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def grace(minutes: int, tick_seconds: float) -> int:
    """Ticks in a row a level must hold to be ``minutes`` long."""

    return max(1, math.ceil(minutes * 60 / tick_seconds))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _over(value: float | None, level: float, opened: bool, margin: float) -> bool:
    if value is None:
        return False
    return value >= (level - margin if opened else level)


def load_checks(
    services: list[dict[str, Any]],
    host: dict[str, Any] | None,
    error_rates: dict[str, float],
    limits: LoadLimits,
    opened: set[str],
    *,
    tick_seconds: float,
    check: Any,
) -> list[Any]:
    """This tick's load checks (``check`` builds one: the watch's ``Check``). ``opened`` names
    the checks with an incident open now (their level is lower by the hysteresis)."""

    if not limits.enabled:
        return []
    held = grace(limits.minutes, tick_seconds)
    found = []

    def judge(name: str, subject: str, cpu: float | None, mem: float | None) -> None:
        for prefix, cpu_level, mem_level, level in (
            (LOAD, limits.cpu_warning, limits.memory_warning, "warning"),
            (LOAD_CRITICAL, limits.cpu_critical, limits.memory_critical, "critical"),
        ):
            key = f"{prefix}:{name}"
            is_open = key in opened
            parts = []
            if _over(cpu, cpu_level, is_open, HYSTERESIS_PCT):
                parts.append(
                    t(
                        "CPU at {pct} % (limit {limit} %)",
                        pct=round(cpu or 0),
                        limit=round(cpu_level),
                    )
                )
            if _over(mem, mem_level, is_open, HYSTERESIS_PCT):
                parts.append(
                    t(
                        "memory at {pct} % (limit {limit} %)",
                        pct=round(mem or 0),
                        limit=round(mem_level),
                    )
                )
            detail = "; ".join(parts) or t(
                "CPU {cpu} %, memory {mem} %",
                cpu="?" if cpu is None else round(cpu),
                mem="?" if mem is None else round(mem),
            )
            found.append(check(key, subject, bool(parts), detail, grace=held, level=level))

    for item in services:
        name = str(item.get("service") or "")
        if not name or item.get("state") != "running":
            continue  # a service down is the service check's incident
        load = item.get("cpu_load_pct")
        judge(name, t("Load of {name}", name=name), _number(load), _number(item.get("mem_pct")))
    if host and (host.get("cpu_pct") is not None or host.get("mem_pct") is not None):
        judge(
            HOST,
            t("Load of the machine"),
            _number(host.get("cpu_pct")),
            _number(host.get("mem_pct")),
        )
    for name, rate in sorted(error_rates.items()):
        value = _number(rate)
        for prefix, level_value, level in (
            (ERRORS, limits.errors_warning, "warning"),
            (ERRORS_CRITICAL, limits.errors_critical, "critical"),
        ):
            key = f"{prefix}:{name}"
            margin = level_value / 5
            bad = _over(value, level_value, key in opened, margin)
            detail = t(
                "{rate} errors a minute (limit {limit})",
                rate="?" if value is None else round(value, 1),
                limit=round(level_value, 1),
            )
            subject = t("Errors of {name}", name=name)
            found.append(check(key, subject, bad, detail, grace=held, level=level))
    return found
