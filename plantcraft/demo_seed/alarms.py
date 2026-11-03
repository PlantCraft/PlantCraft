"""PlantCraft Alarms: the example rules, the philosophy, two days of the pressure alarm's past and
a silence on U-300."""

from __future__ import annotations

import time
from typing import Any

from .base import Http, SeedError, Suite, log, wait_until
from .historian import BACKFILL_WAIT

# PlantCraft Alarms --------------------------------------------------------------------------

ALARM_REPLAY_HOURS = 48
ALARM_OPERATOR = "marina.costa"
U100 = "group:u-100-operations"
U200 = "group:u-200-operations"
INSTRUMENTS = "group:instrumentation"
ON_CALL = "group:on-call"
PROCESS = "group:process-engineering"
SUPERVISOR = "user:marina.costa"
# The installation's own clock (Alarms resolves "local" where it is used).
PLANT_ZONE = "local"
DAY_SHIFT = [{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:00", "end": "17:00"}]
TO_COORDINATOR = [{"after_minutes": 15, "recipients": ["coordinator"], "email": True}]
# The alarm a value rule shows from the start: PIC-1202's limit is the value its archived minutes
# of the last two days stay below this share of the time, so the replayed past holds its peaks.
PRESSURE_LOOP = "PIC-1202"
PRESSURE_QUANTILE = 0.98


# The example rules ("uns 5 alarmes, só para ter como exemplo"; round 11:
# one in Python too): what the apps report becomes an alarm only by a rule,
# and one rule covers a whole unit.
def _simple(*conditions: dict[str, Any], clear_after: float = 0.0) -> dict[str, Any]:
    """A rule's Simple form (Alarms round 11): its conditions, joined by and."""

    return {
        "editor": "simple",
        "simple": {"conditions": list(conditions), "clear_after_seconds": clear_after},
    }


def _event(kinds: list[str], *, about: str = "subject", **fields: Any) -> dict[str, Any]:
    severities = fields.pop("severities", [])
    event = {"kinds": kinds, "severities": severities, "about": about}
    return {"input": "event", "event": event, **fields}


ALARM_RULES: list[dict[str, Any]] = [
    {
        "name": "Analytics monitor failed",
        "creates": "notice",
        "priority": "high",
        "where": {},
        **_simple(
            _event(
                ["linkcraft.run.failed", "linkcraft.schedule.stalled"],
                about="any",
                test="count",
                count=1,
                window_minutes=120,
            )
        ),
        "owner": PROCESS,
        "discipline": "process",
        "notify": {"recipients": ["owner"], "group_seconds": 300, "repeat_minutes": 0},
        "cause": "An Analytics monitor could not run, or stopped running.",
        "consequence": "Its loops are not judged: a problem on them goes unseen.",
        "action": "Open the monitor's last run in Analytics and fix what it says.",
    },
    {
        "name": "Loop critical for over 1 h",
        "creates": "alarm",
        "priority": "medium",
        "where": {"under": ["U-100"]},
        **_simple(
            _event(
                ["linkcraft.status.changed"],
                severities=["critical"],
                test="open",
                for_seconds=3600,
            )
        ),
        "owner": PROCESS,
        "discipline": "process",
        "notify": {"recipients": ["owner"], "group_seconds": 300, "repeat_minutes": 240},
        "cause": "Analytics has found the loop critical for over an hour: not a one-off.",
        "consequence": "The loop keeps disturbing the unit (oscillation, a sticky valve).",
        "action": "Open the loop in Analytics, read the finding and plan the fix with the engineer.",
    },
    {
        "name": "PIC-1202 pressure high",
        "creates": "alarm",
        "priority": "high",
        "where": {"assets": [PRESSURE_LOOP]},
        # The limit and deadband are set from the archive (``_pressure_limit``).
        **_simple(
            {
                "input": "value",
                "value": {"role": "pv", "unit": ""},
                "op": ">=",
                "limit": None,
                "deadband": 0.0,
                "for_seconds": 30.0,
            },
            clear_after=60.0,
        ),
        "owner": U200,
        "discipline": "process",
        "notify": {
            "recipients": [U200],
            "email": True,
            "group_seconds": 120,
            "repeat_minutes": 60,
            "escalations": TO_COORDINATOR,
        },
        "cause": "The pressure loop oscillates: its peaks cross the limit.",
        "consequence": "Relief valve lifts; flaring and product loss.",
        "action": "Put PIC-1202 in manual at its average output and call the process engineer.",
    },
    {
        "name": "No data from the plant",
        "creates": "notice",
        "priority": "medium",
        "where": {"under": ["U-100"]},
        **_simple(_event(["histcraft.point.no_data"], test="open", for_seconds=600)),
        "owner": INSTRUMENTS,
        "discipline": "instrumentation",
        "notify": {
            "recipients": [INSTRUMENTS],
            "group_seconds": 600,
            "repeat_minutes": 0,
            "hours_mode": "inside",
            "hours": DAY_SHIFT,
            "timezone": PLANT_ZONE,
        },
        "cause": "A Unit 100 measurement sent nothing for 10 minutes.",
        "consequence": "Its loop and its alarms run blind.",
        "action": "Check the transmitter and the collector in Historian (Sources).",
    },
    {
        "name": "Loop finding open for a day",
        "creates": "notice",
        "priority": "low",
        "where": {"anywhere": True},
        **_simple(
            _event(
                ["linkcraft.finding.opened", "linkcraft.finding.closed"],
                test="open",
                for_seconds=24 * 3600,
            )
        ),
        "owner": INSTRUMENTS,
        "discipline": "instrumentation",
        "notify": {"recipients": ["owner"], "group_seconds": 600, "repeat_minutes": 0},
        "cause": "An Analytics finding on the loop (a sticking valve, an oscillation) is open for a day.",
        "consequence": "The loop cycles; the valve wears and the product varies.",
        "action": "Plan the loop's fix (valve packing, positioner, tuning) with instrumentation.",
    },
]


# The other way to write a rule (Alarms round 11): a Python block over a few values.
def _node(node_id: str, block: str, x: int, y: int, label: str = "", **parameters: Any) -> dict:
    return {
        "id": node_id,
        "block": block,
        "label": label or node_id,
        "x": x,
        "y": y,
        "parameters": parameters,
    }


def _wire(source: str, source_port: str, target: str, target_port: str) -> dict[str, str]:
    return {
        "source": source,
        "source_port": source_port,
        "target": target,
        "target_port": target_port,
    }


SATURATION_CODE = """def check(inputs):
    # A valve at its end (open or shut) while the loop is still far from its setpoint.
    if inputs.op is None or inputs.pv is None or inputs.sp is None:
        return False, ""
    far = abs(inputs.pv - inputs.sp) > 0.05 * max(abs(inputs.sp), 1.0)
    if inputs.op >= 98 and far:
        return True, f"valve wide open ({inputs.op:.0f} %), PV {inputs.pv:.4g} vs SP {inputs.sp:.4g}"
    if inputs.op <= 2 and far:
        return True, f"valve shut ({inputs.op:.0f} %), PV {inputs.pv:.4g} vs SP {inputs.sp:.4g}"
    return False, ""
"""
SATURATION_DIAGRAM = {
    "version": 2,
    "nodes": [
        _node("pv", "alarm.value", 0, 0, "pv", role="pv"),
        _node("sp", "alarm.value", 0, 150, "sp", role="sp"),
        _node("op", "alarm.value", 0, 300, "op", role="op"),
        _node("python", "alarm.python", 300, 150, "Python", code=SATURATION_CODE),
        _node("alarm", "alarm.raise", 600, 150, "Raise", clear_after_seconds=300.0),
    ],
    "edges": [
        _wire("pv", "value", "python", "values"),
        _wire("sp", "value", "python", "values"),
        _wire("op", "value", "python", "values"),
        _wire("python", "condition", "alarm", "condition"),
    ],
}
ALARM_RULES += [
    {
        "name": "U-100 measurement frozen",
        "creates": "notice",
        "priority": "low",
        "where": {"under": ["U-100"]},
        # A frozen value (owner's review, 2026-10-27: Blocks retired): did not change for 30 min.
        **_simple(
            {
                "input": "value",
                "value": {"role": "pv", "unit": "", "name": "PV"},
                "op": "unchanged",
                "for_seconds": 1800,
            },
            clear_after=60.0,
        ),
        "owner": INSTRUMENTS,
        "discipline": "instrumentation",
        "notify": {"enabled": False},
        "cause": "A Unit 100 PV has not moved for 30 minutes: a stuck transmitter or a frozen tag.",
        "consequence": "Its loop controls on a value that no longer follows the process.",
        "action": "Compare with the field reading and check the transmitter and its tag.",
    },
    {
        "name": "Valve saturated, loop off setpoint",
        "creates": "alarm",
        "priority": "medium",
        "where": {"under": ["U-100"]},
        "editor": "python",
        "diagram": SATURATION_DIAGRAM,
        "owner": PROCESS,
        "discipline": "process",
        "notify": {"recipients": ["owner"], "group_seconds": 300, "repeat_minutes": 240},
        "cause": "The valve is at its end and the loop still cannot reach its setpoint.",
        "consequence": "The loop has lost control: the unit runs off its target.",
        "action": "Check the valve's capacity and the setpoint; bypass or reduce the load.",
    },
]
ALARM_PHILOSOPHY: dict[str, Any] = {
    "statement": (
        "An alarm tells an operator of an abnormal situation that needs an action within the "
        "time its priority gives: critical at once, high within the hour, medium and low within "
        "the shift. Every alarm names its cause, its consequence and the action, and has one "
        "responsible. What needs no action is an alert. A rule that chatters or stands for more "
        "than a day is reviewed with its owner."
    ),
    "digest_times": ["07:00", "19:00"],
    "timezone": PLANT_ZONE,
}
ALARM_SILENCE = {
    "areas": ["U-300"],
    "minutes": 24 * 60,
    "reason": "Sulfur recovery train 2 in planned maintenance (permit 2291)",
}


def _pressure_limit(alarm: Http, suite: Suite) -> tuple[float, float]:
    """PIC-1202's high limit and deadband. From the archive's last two days, as the replay reads
    them (one value a minute), so the replayed past holds occurrences: the
    ``PRESSURE_QUANTILE`` of those values (a short archive: what it holds)."""

    archived = wait_until(
        f"{PRESSURE_LOOP}'s archive", lambda: _pressure_archive(suite) or None, suite.wait, 1.0
    )
    ordered = sorted(archived)
    limit = ordered[int(PRESSURE_QUANTILE * (len(ordered) - 1))]
    spread = ordered[int(0.75 * (len(ordered) - 1))] - ordered[int(0.25 * (len(ordered) - 1))]
    return float(f"{limit:.4g}"), float(f"{max(spread / 8, 1e-6):.3g}")


def _pressure_archive(suite: Suite) -> list[float]:
    """PIC-1202's PV over the replayed hours, one value a minute (empty when unreadable)."""

    try:
        admin = suite.session(suite.admin, suite.password)
        asset = admin.get(f"/api/assets/{PRESSURE_LOOP}") or {}
        signal = next(
            f"{item['source_id']}:{item['signal_id']}"
            for item in asset.get("signals") or []
            if item.get("role") == "pv"
        )
        end = time.time()
        answer = admin.post(
            "/api/v1/series",
            {
                "signals": [signal],
                "start": _iso(end - ALARM_REPLAY_HOURS * 3600),
                "end": _iso(end),
                "step": 60,
            },
        )
    except (SeedError, StopIteration, KeyError, TypeError):
        return []
    series = (answer or {}).get("series") or [{}]
    return [float(value) for value in series[0].get("v") or [] if isinstance(value, (int, float))]


def _iso(moment: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))


def alarmcraft(alarm: Http, suite: Suite) -> None:
    """Seven example rules (what Analytics reports, a pressure limit, no data from Unit 100, a
    finding still open, a frozen measurement in Blocks, a saturated valve in Python), two days of
    the pressure alarm's past replayed from the archive (acknowledged by the shift supervisor) and
    a silence on U-300. Re-runnable: the rules are set back to the demo's."""

    have = {item["name"]: item for item in alarm.get("/api/rules") or []}
    for body in ALARM_RULES:
        body = dict(body)
        found = have.get(body["name"])
        first = ((body.get("simple") or {}).get("conditions") or [{}])[0]
        if first.get("input") == "value":
            before = ((found or {}).get("simple") or {}).get("conditions") or [{}]
            if before[0].get("limit") is not None:
                limit, deadband = before[0]["limit"], before[0].get("deadband") or 0.0
            else:
                limit, deadband = _pressure_limit(alarm, suite)
            body["simple"] = {
                **body["simple"],
                "conditions": [{**first, "limit": limit, "deadband": deadband}],
            }
        if found is None:
            alarm.post("/api/rules", body)
            log(f"Alarms: rule {body['name']}")
        else:
            alarm.put(
                f"/api/rules/{found['rule_id']}",
                {**body, "base_updated_at": found.get("updated_at")},
            )
    # The installation's alarm philosophy (Alarms 0.5+): the public targets, the plant's shifts.
    status, current = alarm.call("GET", "/api/philosophy", ok=(404,))
    if status == 200 and isinstance(current, dict) and not current.get("updated_by"):
        alarm.call("PUT", "/api/philosophy", {**current["defaults"], **ALARM_PHILOSOPHY})
        log("Alarms: alarm philosophy")
    status, _answer = alarm.call(
        "POST",
        "/api/history/replay",
        {"hours": ALARM_REPLAY_HOURS, "acknowledged_by": ALARM_OPERATOR},
        ok=(404, 405, 503),
    )
    if status == 202:
        state = wait_until(
            "Alarms' history replay",
            lambda: (lambda got: got if not got.get("running") else None)(
                alarm.get("/api/history/replay")
            ),
            max(suite.wait, BACKFILL_WAIT),
        )
        raised = sum(item.get("occurrences", 0) for item in (state.get("alarms") or {}).values())
        log(f"Alarms: {raised} occurrences of the last {ALARM_REPLAY_HOURS} hours replayed")
    if not any(item.get("active") for item in alarm.get("/api/silences") or []):
        alarm.post("/api/silences", ALARM_SILENCE)
        log(f"Alarms: silence on U-300 ({ALARM_SILENCE['reason']})")
    alarm.post("/api/run", ok=(409, 503))
