"""The rule language (``alarms.blocks``, ``alarms.simple``) run by ``engine.run`` on one subject:
limits, deadband, persistence in time and in points, events open and counted, a Python block,
cycles that continue where they stopped, timers between samples; and the performance figures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from alarmcraft.alarms.blocks import check
from alarmcraft.alarms.simple import SimpleLogic, to_diagram
from alarmcraft.engine import run as engine
from alarmcraft.engine.performance import performance

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SIGNAL = "plantcraft:A.PV"
ASSET = engine.Subject("A", "asset", "A", {"id": "A", "signals": {"pv": SIGNAL}}, "A")


def series(values, every: float = 1.0) -> pd.Series:
    return pd.Series(
        values, index=[T0 + timedelta(seconds=every * i) for i in range(len(values))], dtype=float
    )


def value_rule(op: str = ">=", limit: float = 10.0, **fields) -> dict:
    clear = fields.pop("clear_after_seconds", 0.0)
    condition = {"input": "value", "value": {"role": "pv"}, "op": op, "limit": limit, **fields}
    logic = SimpleLogic.model_validate({"conditions": [condition], "clear_after_seconds": clear})
    return to_diagram(logic)


def event_rule(test: str = "open", **fields) -> dict:
    event = {"kinds": [fields.pop("kind", "a.b")], **fields.pop("event", {})}
    condition = {"input": "event", "event": event, "test": test, **fields}
    return to_diagram(SimpleLogic.model_validate({"conditions": [condition]}))


def judge(diagram, values=None, *, every: float = 1.0, state=None, end=None, events=(), **kw):
    data = series(values, every) if values is not None else pd.Series(dtype=float)
    stop = end or (data.index[-1].to_pydatetime() if len(data) else T0)
    return engine.run(
        diagram,
        kw.pop("subject", ASSET),
        state or {},
        series={SIGNAL: data},
        events=list(events),
        end=stop,
        **kw,
    )


def kinds(outcome) -> list[str]:
    return [kind for kind, _ in outcome.transitions]


def test_raises_at_the_limit_and_clears_past_the_deadband():
    found = judge(value_rule(deadband=1.0), [5, 9, 10, 11, 9.5, 9.2, 8.9, 8])
    assert found.transitions == [
        ("raised", T0 + timedelta(seconds=2)),
        ("cleared", T0 + timedelta(seconds=6)),
    ]
    assert found.state["active"] is False and found.value == 8.0 and found.signal == SIGNAL


def test_deadband_stops_chattering():
    noisy = [9.8, 10.1, 9.9, 10.2, 9.7, 10.0, 9.95]
    assert kinds(judge(value_rule(deadband=0.0), noisy)).count("raised") == 3
    assert kinds(judge(value_rule(deadband=0.5), noisy)) == ["raised"]


def test_for_seconds_needs_the_condition_to_hold():
    rule = value_rule(for_seconds=3)
    assert kinds(judge(rule, [11, 11, 9, 11, 11, 11, 9])) == []
    held = judge(rule, [11, 11, 11, 11, 5])
    assert held.transitions[0] == ("raised", T0 + timedelta(seconds=3))


def test_for_points_counts_samples_not_seconds():
    # One point an hour (an app's series): three in a row.
    rule = value_rule(op="<", limit=50, for_points=3)
    found = judge(rule, [40, 40, 60, 40, 40, 40, 60], every=3600)
    assert found.transitions == [
        ("raised", T0 + timedelta(hours=5)),
        ("cleared", T0 + timedelta(hours=6)),
    ]


def test_clear_after_and_low_alarms():
    rule = value_rule(op="<=", limit=2.0, clear_after_seconds=2)
    found = judge(rule, [3, 2, 1, 3, 1, 3, 3, 3, 3])
    assert kinds(found) == ["raised", "cleared"]
    assert found.transitions[1][1] == T0 + timedelta(seconds=7)


def test_cycles_continue_where_they_stopped():
    rule = value_rule()
    first = judge(rule, [11, 11, 11])
    assert kinds(first) == ["raised"] and first.state["active"]
    # The next cycle reads overlapping samples: those already judged count once.
    later = pd.Series([12.0, 5.0], index=[T0 + timedelta(seconds=2), T0 + timedelta(seconds=5)])
    found = engine.run(
        rule, ASSET, first.state, series={SIGNAL: later}, events=[], end=T0 + timedelta(seconds=5)
    )
    assert kinds(found) == ["cleared"]
    again = engine.run(
        rule, ASSET, found.state, series={SIGNAL: later}, events=[], end=T0 + timedelta(seconds=6)
    )
    assert again.transitions == [] and again.state["evaluated_until"].startswith("2026-10-01")


def test_a_late_point_counts_once_when_it_comes():
    # An app writes a run's point when the run ends, stamped earlier than the last cycle.
    rule = value_rule(op="<", limit=50, for_points=1)
    state = {
        "evaluated_until": (T0 + timedelta(minutes=10)).isoformat(),
        "seen": {SIGNAL: T0.isoformat()},
    }
    late = pd.Series([40.0], index=[T0 + timedelta(minutes=5)])
    found = engine.run(
        rule, ASSET, state, series={SIGNAL: late}, events=[], end=T0 + timedelta(minutes=11)
    )
    assert kinds(found) == ["raised"]
    again = engine.run(
        rule, ASSET, found.state, series={SIGNAL: late}, events=[], end=T0 + timedelta(minutes=12)
    )
    assert again.transitions == [] and again.state["active"]


def event(minute: float, phase: str = "instant", **fields) -> dict:
    return {
        "id": int(minute * 10) + 1,
        "at": (T0 + timedelta(minutes=minute)).isoformat(),
        "app": "x",
        "kind": "a.b",
        "subject": "asset:A",
        "phase": phase,
        "key": "k",
        "severity": "critical",
        **fields,
    }


def test_an_open_condition_raises_after_its_time_even_without_samples():
    """A condition open 3 h with "for 1 h" raises an hour after it opened (a Test over the
    last hours has no sample in between: the engine adds the timer's moment)."""

    rule = event_rule(for_seconds=3600)
    found = judge(
        rule,
        events=[event(0, "start"), event(180, "end")],
        end=T0 + timedelta(hours=4),
    )
    assert found.transitions == [
        ("raised", T0 + timedelta(hours=1)),
        ("cleared", T0 + timedelta(hours=3)),
    ]
    assert found.counted == {1, 1801} and found.heard["severity"] == "critical"
    short = judge(rule, events=[event(0, "start"), event(30, "end")], end=T0 + timedelta(hours=4))
    assert short.transitions == []


def test_events_counted_within_the_window():
    rule = event_rule("count", count=2, window_minutes=10)
    found = judge(rule, events=[event(0), event(11), event(16)], end=T0 + timedelta(minutes=40))
    # The second came after the first left the window; the third makes two in 10 minutes,
    # and the alarm clears when the window empties.
    assert found.transitions == [
        ("raised", T0 + timedelta(minutes=16)),
        ("cleared", T0 + timedelta(minutes=21)),
    ]


def test_events_about_another_asset_or_too_mild_do_not_count():
    rule = event_rule("count", count=1, event={"severities": ["critical"]})
    other = event(1, subject="asset:B")
    mild = event(2, severity="warning")
    found = judge(rule, events=[other, mild], end=T0 + timedelta(minutes=5))
    assert found.transitions == [] and found.counted == set()
    anywhere = event_rule("count", count=1, event={"about": "any"})
    assert kinds(judge(anywhere, events=[other], end=T0 + timedelta(minutes=5))) == ["raised"]


def test_an_execution_hears_the_events_of_its_schedule():
    subject = engine.Subject("execution:linkcraft:s1", "execution", "s1", None, "S1", "linkcraft")
    rule = event_rule("count", count=1, kind="linkcraft.run.failed")
    mine = event(1, app="linkcraft", kind="linkcraft.run.failed", payload={"schedule_id": "s1"})
    other = {**mine, "id": 99, "payload": {"schedule_id": "s2"}}
    found = judge(rule, events=[other, mine], end=T0 + timedelta(minutes=5), subject=subject)
    assert kinds(found) == ["raised"] and found.counted == {11}
    assert found.heard["schedule_id"] == "s1"


def test_a_condition_open_before_the_rule_counts():
    rule = event_rule()
    opened = [{**event(0, "start"), "opened_at": T0.isoformat()}]
    found = judge(rule, events=[], end=T0 + timedelta(minutes=1), open_now=opened)
    assert kinds(found) == ["raised"]


def python_rule(code: str) -> dict:
    return {
        "version": 2,
        "nodes": [
            {"id": "v", "block": "alarm.value", "parameters": {"role": "pv"}, "label": "pv"},
            {"id": "p", "block": "alarm.python", "parameters": {"code": code}},
            {"id": "r", "block": "alarm.raise", "parameters": {}},
        ],
        "edges": [
            {"source": "v", "source_port": "value", "target": "p", "target_port": "values"},
            {"source": "p", "source_port": "condition", "target": "r", "target_port": "condition"},
        ],
    }


def test_a_python_block_answers_with_a_sentence():
    seen = []

    def runner(node_id, code, inputs):
        seen.append(inputs)
        return inputs["pv"] > 10, f"pv is {inputs['pv']:g}"

    found = judge(python_rule("def check(inputs):\n    return True, ''\n"), [5, 12], python=runner)
    assert kinds(found) == ["raised"] and found.message == "pv is 12"
    assert seen == [{"pv": 12.0}]
    # Without a runner (a replay), a Python rule cannot be judged and says why.
    assert judge(python_rule("x"), [5], python=None).unknown


def test_a_diagram_has_one_raise():
    assert check(value_rule()).valid
    no_raise = {"version": 2, "nodes": [], "edges": []}
    assert not check(no_raise).valid
    with pytest.raises(ValueError):
        SimpleLogic.model_validate({"conditions": []})
    with pytest.raises(ValueError):
        SimpleLogic.model_validate({"conditions": [{"input": "value", "value": {"role": "pv"}}]})


def test_the_simple_form_reads_as_a_sentence():
    logic = SimpleLogic.model_validate(
        {
            "conditions": [
                {"input": "value", "value": {"role": "pv", "unit": "m3/h"}, "op": ">", "limit": 50,
                 "for_seconds": 300},
                {"input": "event", "event": {"kinds": ["linkcraft.run.failed"]}, "test": "count",
                 "count": 3, "window_minutes": 60},
            ],
            "combine": "or",
            "clear_after_seconds": 600,
        }
    )  # fmt: skip
    assert logic.sentence() == (
        "pv > 50 m3/h for 5 min or Analytics run failed happened 3 times in 1 h;"
        " clears after 10 min back to normal"
    )
    assert check(to_diagram(logic)).valid


def occurrence(alarm_id: str, minute: float, priority: str = "low", **fields) -> dict:
    return {
        "alarm_id": alarm_id,
        "priority": priority,
        "started_at": (T0 + timedelta(minutes=minute)).isoformat(),
        "ended_at": (T0 + timedelta(minutes=minute + 1)).isoformat(),
        **fields,
    }


def test_performance_figures():
    found = [occurrence("a", 0.1 * i) for i in range(12)]  # a flood, and chattering
    found += [occurrence("b", 300, "high", acked_at=(T0 + timedelta(minutes=301)).isoformat())]
    found += [occurrence("c", 60, "medium", ended_at=None)]  # still active at the end: stale
    result = performance(found, T0, T0 + timedelta(hours=26), names={"a": "A"})
    figures = {item["id"]: item for item in result["figures"]}
    assert result["total"] == 14
    assert figures["peak"]["value"] == 12 and figures["peak"]["status"] == "warning"
    assert figures["flood"]["value"] > 0
    assert figures["chattering"]["value"] == 1 and figures["chattering"]["status"] == "alarm"
    assert [item["name"] for item in result["chattering"]] == ["A"]
    assert figures["stale"]["value"] == 1
    assert result["top"][0] == {
        "alarm_id": "a",
        "name": "A",
        "count": 12,
        "share": 85.7,
        "chattering": True,
        "priority": "low",
    }
    assert len(result["hourly"]) == 26 and result["hourly"][0]["counts"] == {"low": 12}
    assert result["hourly"][1]["counts"] == {"medium": 1}
    assert result["hourly"][5] == {
        "at": (T0 + timedelta(hours=5)).isoformat(),
        "counts": {"high": 1},
    }
    shares = {item["priority"]: item["share"] for item in result["priorities"]}
    assert shares == {"high": 7.1, "medium": 7.1, "low": 85.7}
    assert result["mean_ack_seconds"] == 60.0


def test_performance_of_a_quiet_period():
    result = performance([], T0, T0 + timedelta(hours=1))
    assert result["total"] == 0 and all(item["status"] == "ok" for item in result["figures"])
    assert result["hourly"] == [{"at": T0.isoformat(), "counts": {}}]


def test_the_hourly_counts_fall_on_whole_hours():
    # A day that starts at 10:30: 25 hours, the first and the last partial.
    start = T0 + timedelta(hours=10, minutes=30)
    found = [occurrence("a", 10 * 60 + 40, "critical"), occurrence("b", 34 * 60 + 20)]
    found += [occurrence("c", 9 * 60)]  # before the period: not counted
    result = performance(found, start, start + timedelta(hours=24))
    hours = result["hourly"]
    assert len(hours) == 25 and hours[0]["at"] == (T0 + timedelta(hours=10)).isoformat()
    assert hours[0]["counts"] == {"critical": 1} and hours[-1]["counts"] == {"low": 1}
    assert sum(sum(hour["counts"].values()) for hour in hours) == result["total"] == 2
