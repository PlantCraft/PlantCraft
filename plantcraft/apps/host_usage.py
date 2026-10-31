"""The machine's own load, and each container's load against what it was given.

``docker stats`` writes a container's CPU as a percentage of **one** core: a server given
4 CPUs and busy on all of them reads 400 %. A limit like "warn at 80 %" means nothing on that
scale, so the installer adds, for each container, ``cpu_load_pct``: its CPU as a share of the
CPUs it may use (its Compose ``cpus`` limit, or every CPU of the machine when it has none),
0 to 100. The machine itself is read from ``/proc`` (the kernel's counters are not per
container): its CPU over the last interval, its memory in use and its CPU count. On Docker
Desktop the "machine" is the Linux virtual machine Docker runs in, which is what the suite's
containers share. See docs/operations.md, section 4.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def cpu_times(text: str) -> tuple[int, int] | None:
    """``(total, idle)`` jiffies from ``/proc/stat``'s first line (idle counts iowait)."""

    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "cpu":
            try:
                values = [int(value) for value in parts[1:]]
            except ValueError:
                return None
            if len(values) < 4:
                return None
            # user nice system idle iowait irq softirq steal (guest is already in user)
            total = sum(values[:8])
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            return total, idle
    return None


def memory(text: str) -> dict[str, int] | None:
    """``{"total_bytes", "available_bytes"}`` from ``/proc/meminfo``."""

    found: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if name in ("MemTotal", "MemAvailable"):
            try:
                found[name] = int(rest.split()[0]) * 1024
            except (IndexError, ValueError):
                return None
    if "MemTotal" not in found or "MemAvailable" not in found or found["MemTotal"] <= 0:
        return None
    return {"total_bytes": found["MemTotal"], "available_bytes": found["MemAvailable"]}


def load_pct(cpu_pct: float | None, cpus: float | None, host_cpus: int | None) -> float | None:
    """A container's CPU (``docker stats``, % of one core) as a share of the CPUs it may use."""

    if cpu_pct is None:
        return None
    allotted = cpus if cpus and cpus > 0 else host_cpus
    if not allotted:
        return None
    if host_cpus:
        allotted = min(allotted, host_cpus)  # a limit above the machine's CPUs is the machine
    return round(max(0.0, min(100.0, cpu_pct / allotted)), 1)


def nano_cpus(text: str) -> float | None:
    """Docker's ``HostConfig.NanoCpus`` as CPUs; None when the container has no CPU limit."""

    try:
        value = int(str(text).strip() or "0")
    except ValueError:
        return None
    return round(value / 1e9, 3) if value > 0 else None


class HostSampler:
    """The machine's CPU between two calls (the first answers None), memory and CPU count."""

    def __init__(self, proc: str | Path = "/proc"):
        self.proc = Path(proc)
        self._last: tuple[int, int] | None = None

    def _read(self, name: str) -> str:
        try:
            return (self.proc / name).read_text(encoding="utf-8")
        except OSError:
            return ""

    def sample(self) -> dict[str, Any]:
        cpus = os.cpu_count()
        found: dict[str, Any] = {"cpus": cpus, "cpu_pct": None, "mem_pct": None}
        times = cpu_times(self._read("stat"))
        if times is not None:
            if self._last is not None:
                total = times[0] - self._last[0]
                idle = times[1] - self._last[1]
                if total > 0:
                    found["cpu_pct"] = round(max(0.0, min(100.0, 100 * (1 - idle / total))), 1)
            self._last = times
        mem = memory(self._read("meminfo"))
        if mem is not None:
            used = mem["total_bytes"] - mem["available_bytes"]
            found.update(
                mem_total_bytes=mem["total_bytes"],
                mem_used_bytes=used,
                mem_pct=round(100 * used / mem["total_bytes"], 1),
            )
        load = self._read("loadavg").split()
        try:
            found["load_1m"] = float(load[0]) if load else None
        except ValueError:
            found["load_1m"] = None
        return found
