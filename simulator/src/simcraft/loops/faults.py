"""Scheduled faults for the loop portfolio, with the answer key kept apart.

An instructor writes a fault schedule (JSON): which fault, on which loop, from when and for how
long. The server applies it, so the trainee sees only the plant: the tags, their values and
their status codes. Nothing on OPC UA names a fault. The answer key is the schedule turned into
what happened and what to look for (``answer_key``, ``simcraft loops faults key``). It also
records what the server saw when each fault began, and it stays with the instructor.

The faults are the common faults of a control loop in public alarm management and loop
monitoring literature:

| Fault | What it does |
|---|---|
| ``sensor_bias`` | the transmitter reads ``magnitude`` off the true value (a drift or a bad calibration) |
| ``sensor_frozen`` | the transmitter holds its value from the start (a frozen PV) |
| ``bad_quality`` | the PV is published with status ``Bad`` (a failed transmitter or link) |
| ``valve_stuck`` | the valve holds its position from the start; the controller output keeps moving |
| ``load_step`` | the process takes a step of ``magnitude`` in PV units (a feed or load change) |
| ``manual`` | the loop is left in manual; its output holds where it was |

Times are UTC. A fault is active from ``start`` for ``duration_minutes``, or until the server
stops when no duration is given. The same schedule and clock give the same values every time,
so the simulator stays deterministic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

FAULTS: dict[str, str] = {
    "sensor_bias": "The transmitter reads off the true value by the magnitude.",
    "sensor_frozen": "The transmitter holds its value from the start.",
    "bad_quality": "The PV is published with status Bad.",
    "valve_stuck": "The valve holds its position; the controller output keeps moving.",
    "load_step": "The process takes a step of the magnitude (in PV units).",
    "manual": "The loop is left in manual; its output holds where it was.",
}
# What a trainee should notice, for the answer key.
SYMPTOMS: dict[str, str] = {
    "sensor_bias": "PV and SP agree while the process moved: OP shifted with no load change, "
    "and the downstream values or a redundant measurement disagree.",
    "sensor_frozen": "PV stops moving (no noise, no change) while OP keeps changing; the "
    "controller winds up.",
    "bad_quality": "PV status Bad: the value cannot be used; alarms on it should say so.",
    "valve_stuck": "OP keeps moving but PV does not answer it; the error grows and the "
    "integral winds up.",
    "load_step": "PV leaves SP at once and OP moves to bring it back: a real process change, "
    "the instrument is fine.",
    "manual": "MODE reads MAN; OP stops following the error and PV drifts from SP.",
}
NEEDS_MAGNITUDE = {"sensor_bias", "load_step"}
MAX_FAULTS = 200


class FaultScheduleError(ValueError):
    """A schedule that cannot be applied; the message says which entry and why."""


@dataclass(frozen=True)
class Fault:
    fault_id: str
    loop_id: str
    kind: str
    start: datetime
    duration_minutes: float | None = None
    magnitude: float = 0.0
    note: str = ""

    @property
    def end(self) -> datetime | None:
        if self.duration_minutes is None:
            return None
        return self.start + timedelta(minutes=self.duration_minutes)

    def active(self, moment: datetime) -> bool:
        end = self.end
        return self.start <= moment and (end is None or moment < end)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.fault_id,
            "loop": self.loop_id,
            "fault": self.kind,
            "start": self.start.isoformat().replace("+00:00", "Z"),
            "duration_minutes": self.duration_minutes,
            "magnitude": self.magnitude,
            "note": self.note,
        }


def _moment(text: Any, where: str) -> datetime:
    if not isinstance(text, str) or not text.strip():
        raise FaultScheduleError(f"{where}: start is a UTC time like 2026-11-02T13:30:00Z")
    try:
        found = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise FaultScheduleError(
            f"{where}: start {text!r} is not a time like 2026-11-02T13:30:00Z"
        ) from exc
    if found.tzinfo is None:
        raise FaultScheduleError(f"{where}: start needs its zone, Z for UTC")
    return found.astimezone(UTC)


def parse_schedule(payload: Any, loops: set[str]) -> list[Fault]:
    """The faults of a schedule (``{"faults": [...]}`` or a bare list), checked against the
    portfolio's loops."""

    items = payload.get("faults") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise FaultScheduleError('a schedule is {"faults": [...]}')
    if len(items) > MAX_FAULTS:
        raise FaultScheduleError(f"at most {MAX_FAULTS} faults in a schedule")
    found: list[Fault] = []
    seen: set[str] = set()
    for number, item in enumerate(items, start=1):
        where = f"fault {number}"
        if not isinstance(item, dict):
            raise FaultScheduleError(f"{where}: an object with loop, fault and start")
        unknown = set(item) - {"id", "loop", "fault", "start", "duration_minutes", "magnitude",
                               "note"}  # fmt: skip
        if unknown:
            raise FaultScheduleError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
        fault_id = str(item.get("id") or f"F{number}").strip()[:40]
        where = f"fault {fault_id}"
        if fault_id in seen:
            raise FaultScheduleError(f"{where}: the id is used twice")
        seen.add(fault_id)
        loop_id = str(item.get("loop") or "").strip()
        if loop_id not in loops:
            raise FaultScheduleError(f"{where}: no loop {loop_id!r} in the portfolio")
        kind = str(item.get("fault") or "").strip()
        if kind not in FAULTS:
            raise FaultScheduleError(
                f"{where}: fault {kind!r} is not one of {', '.join(sorted(FAULTS))}"
            )
        duration = item.get("duration_minutes")
        if duration is not None:
            if isinstance(duration, bool) or not isinstance(duration, int | float):
                raise FaultScheduleError(f"{where}: duration_minutes is a number")
            if not 0 < float(duration) <= 30 * 24 * 60:
                raise FaultScheduleError(f"{where}: duration_minutes from 0 to 30 days")
            duration = float(duration)
        magnitude = item.get("magnitude", 0.0)
        if isinstance(magnitude, bool) or not isinstance(magnitude, int | float):
            raise FaultScheduleError(f"{where}: magnitude is a number")
        if kind in NEEDS_MAGNITUDE and not magnitude:
            raise FaultScheduleError(f"{where}: {kind} needs a magnitude (in PV units)")
        found.append(
            Fault(
                fault_id=fault_id,
                loop_id=loop_id,
                kind=kind,
                start=_moment(item.get("start"), where),
                duration_minutes=duration,
                magnitude=float(magnitude),
                note=str(item.get("note") or "")[:300],
            )
        )
    by_loop: dict[str, list[Fault]] = {}
    for fault in found:
        for other in by_loop.get(fault.loop_id, []):
            if other.kind == fault.kind and _overlap(other, fault):
                raise FaultScheduleError(
                    f"fault {fault.fault_id}: overlaps {other.fault_id} ({fault.kind} on "
                    f"{fault.loop_id})"
                )
        by_loop.setdefault(fault.loop_id, []).append(fault)
    return sorted(found, key=lambda item: (item.start, item.fault_id))


def _overlap(first: Fault, second: Fault) -> bool:
    first_end, second_end = first.end, second.end
    return (first_end is None or second.start < first_end) and (
        second_end is None or first.start < second_end
    )


def load_schedule(path: str | Path, loops: set[str]) -> list[Fault]:
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FaultScheduleError(f"no fault schedule at {path}") from exc
    except json.JSONDecodeError as exc:
        raise FaultScheduleError(f"{path} is not JSON: {exc}") from exc
    return parse_schedule(payload, loops)


def active_faults(faults: list[Fault], loop_id: str, moment: datetime) -> list[Fault]:
    return [fault for fault in faults if fault.loop_id == loop_id and fault.active(moment)]


def answer_key(faults: list[Fault], fired: dict[str, dict[str, Any]] | None = None) -> dict:
    """The instructor's answer key: each fault, when, what it did and what to look for, with
    what the server saw when it began (``fired``, from the state store) once it ran."""

    fired = fired or {}
    return {
        "kind": "simcraft.loops.fault-answer-key",
        "version": 1,
        "faults": [
            {
                **fault.to_dict(),
                "end": fault.end.isoformat().replace("+00:00", "Z") if fault.end else None,
                "what": FAULTS[fault.kind],
                "symptoms": SYMPTOMS[fault.kind],
                "fired": fired.get(fault.fault_id),
            }
            for fault in faults
        ],
    }


def answer_key_markdown(key: dict) -> str:
    lines = [
        "# Fault answer key",
        "",
        "For the instructor only: the trainee sees the tags, never this list.",
        "",
        "| Id | Loop | Fault | From (UTC) | To (UTC) | Magnitude | Fired | Look for |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in key["faults"]:
        fired = item.get("fired") or {}
        fired_text = fired.get("at", "not yet") if fired else "not yet"
        lines.append(
            f"| {item['id']} | {item['loop']} | {item['fault']} | {item['start']} | "
            f"{item['end'] or 'until stopped'} | {item['magnitude']:g} | {fired_text} | "
            f"{item['symptoms']} |"
        )
    return "\n".join(lines) + "\n"
