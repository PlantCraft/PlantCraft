"""The alarm blocks: what a rule's diagram is made of (Alarms round 11).

Every rule is a small diagram of the suite's blocks (``plantcraft_sdk.blocks``): inputs (a
value, an event), logic (compare, and, or, not, rate of change...), persistence (for at least,
times in a window) and one **Raise an alarm** block. The Simple form, the Blocks editor and the
Python block are three ways to write the same diagram (``alarms.simple`` writes it from the
form), so testing, history and silences work alike for all three.

A diagram runs once per subject (an asset, a Link execution) per cycle, on the moments of that
cycle: the samples of its values, the times of its events and the cycle's end. A value is a
``series`` on those moments (held between samples); a condition is ``intervals`` (true or false
at each moment). Blocks that remember (a deadband, a persistence, a count of events) keep their
memory in ``Context.state``, saved with the alarm, so a cycle starts where the last one ended.

What the engine hands the blocks, in ``Context.extra``:

| Key | What |
|---|---|
| ``index`` | the moments of this run (``pandas.DatetimeIndex``, UTC, sorted) |
| ``samples`` | the moments that are samples or events (persistence by points counts these) |
| ``series`` | the new samples of each signal (``{signal id: pandas.Series}``) |
| ``resolve`` | ``resolve(signal, role)``: the signal id a value block reads on this subject |
| ``events`` | the suite's events of this run, oldest first, and ``about(event, about)`` |
| ``open_now`` | the conditions open now (a new alarm starts from them) |
| ``python`` | ``python(node_id, code, inputs)``: a Python block's answer, run isolated |
| ``names`` | each Python block's input names (the blocks wired to it, by label) |
| ``transitions`` | where Raise an alarm writes ``("raised" or "cleared", moment)`` |
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import (
    Block,
    BlockDocs,
    BlockSpec,
    Context,
    NoData,
    NoParameters,
    Plan,
    compile_diagram,
    inport,
    outport,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alarmcraft.alarms.model import EVENT_KIND, kind_matches
from alarmcraft.i18n import t

LIBRARY = "alarm"
ALARM_BLOCK = "alarm.raise"
PYTHON_BLOCK = "alarm.python"
VALUE_BLOCK = "alarm.value"
EVENT_BLOCKS = ("alarm.event_open", "alarm.event_count")
# A Python block runs at most this often (its answer holds in between).
PYTHON_EVERY_SECONDS = 60
MAX_HITS = 500
# A signal id written for "this asset": {asset} is the subject's id.
ASSET = "{asset}"


def _iso(moment: pd.Timestamp | None) -> str | None:
    return None if moment is None else pd.Timestamp(moment).isoformat()


def _time(text: Any) -> pd.Timestamp | None:
    if not text:
        return None
    try:
        moment = pd.Timestamp(str(text))
    except ValueError:
        return None
    return moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")


def _index(context: Context) -> pd.DatetimeIndex:
    return context.extra["index"]


def _samples(context: Context) -> set:
    return context.extra.get("samples") or set()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# Inputs ----------------------------------------------------------------------------------


class ValueParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: str = Field(
        default="",
        max_length=320,
        description="The signal or app series read; {asset} stands for each asset of the rule.",
    )
    role: str = Field(
        default="",
        max_length=40,
        pattern=r"^([a-z][a-z0-9_]{0,39})?$",
        description="Or the asset's signal with this role (pv, sp, op), on each asset.",
    )
    unit: str = Field(default="", max_length=40, description="The value's unit, shown in words.")


def run_value(inputs: dict[str, Any], params: ValueParams, context: Context) -> dict[str, Any]:
    try:
        signal = context.extra["resolve"](params.signal, params.role)
    except LookupError as exc:
        return {"value": NoData(str(exc), context.node_id)}
    index = _index(context)
    state = context.state
    found = pd.Series(np.nan, index=index, dtype=float)
    new = (context.extra.get("series") or {}).get(signal)
    if new is not None and len(new):
        inside = new[new.index.isin(index)]
        found.loc[inside.index] = inside.to_numpy(dtype=float)
    found = found.ffill()
    held = _number(state.get("held"))
    if held is not None:
        found = found.fillna(held)
    if found.isna().all():
        return {"value": NoData(t("No value yet from {signal}.", signal=signal), context.node_id)}
    state["held"] = float(found.dropna().iloc[-1])
    context.extra.setdefault("shown", {})[context.node_id] = (state["held"], params.unit, signal)
    return {"value": found}


def _kinds(values: list[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        value = str(value or "").strip()
        if not EVENT_KIND.match(value) or ("*" in value and not value.endswith(".*")):
            raise ValueError("an event kind like linkcraft.run.failed, or linkcraft.finding.*")
        if value not in found:
            found.append(value)
    return found


class EventParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kinds: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="The kinds of event that count, such as histcraft.point.no_data.",
    )
    severities: list[Literal["warning", "critical"]] = Field(
        default_factory=list,
        max_length=2,
        description="Only events of these severities count (all when none is chosen).",
    )
    about: str = Field(
        default="subject",
        max_length=320,
        description="Whose events: subject (each asset or execution of the rule), any, or a ref.",
    )

    @field_validator("kinds")
    @classmethod
    def _valid(cls, value: list[str]) -> list[str]:
        return _kinds(value)


class CountParams(EventParams):
    window_minutes: int = Field(
        default=60, ge=1, le=7 * 24 * 60, description="Events are counted over this many minutes."
    )


def _matches(params: EventParams, event: dict[str, Any], context: Context) -> bool:
    if not kind_matches(params.kinds, str(event.get("kind") or "")):
        return False
    return bool(context.extra["about"](event, params.about))


def _severe(params: EventParams, event: dict[str, Any]) -> bool:
    if not params.severities:
        return True
    return str(event.get("severity") or "") in params.severities


def _condition_key(event: dict[str, Any]) -> str:
    key = str(event.get("key") or "")
    return f"{event.get('app')}|{key}" if key else f"{event.get('app')}|{event.get('kind')}"


def run_event_open(inputs: dict[str, Any], params: EventParams, context: Context) -> dict[str, Any]:
    index = _index(context)
    state = context.state
    if "open" not in state:
        state["open"] = {
            _condition_key({**item, "key": item.get("key") or item.get("condition_key")}): str(
                item.get("opened_at") or ""
            )
            for item in context.extra.get("open_now") or []
            if _matches(params, item, context) and _severe(params, item)
        }
    opened: dict[str, str] = dict(state["open"])
    events = [item for item in context.extra.get("events") or [] if _matches(params, item, context)]
    found = []
    position = 0
    for moment in index:
        pulse = False
        while position < len(events) and (_time(events[position].get("at")) or moment) <= moment:
            event = events[position]
            position += 1
            phase = str(event.get("phase") or "instant")
            key = _condition_key(event)
            if phase == "end" or (phase == "start" and not _severe(params, event)):
                opened.pop(key, None)
            elif phase == "start":
                opened[key] = str(event.get("at") or "")
            elif _severe(params, event):
                pulse = True
        found.append(bool(opened) or pulse)
    state["open"] = opened
    return {"open": pd.Series(found, index=index, dtype=bool)}


def run_event_count(
    inputs: dict[str, Any], params: CountParams, context: Context
) -> dict[str, Any]:
    index = _index(context)
    state = context.state
    window = pd.Timedelta(minutes=params.window_minutes)
    hits = [moment for moment in (_time(item) for item in state.get("hits") or []) if moment]
    events = [
        item
        for item in context.extra.get("events") or []
        if _matches(params, item, context)
        and str(item.get("phase") or "instant") != "end"
        and _severe(params, item)
    ]
    found = []
    position = 0
    for moment in index:
        while position < len(events) and (_time(events[position].get("at")) or moment) <= moment:
            hits.append(_time(events[position].get("at")) or moment)
            position += 1
        hits = [item for item in hits if item > moment - window]
        found.append(float(len(hits)))
    state["hits"] = [_iso(item) for item in hits[-MAX_HITS:]]
    return {"count": pd.Series(found, index=index, dtype=float)}


# Logic -----------------------------------------------------------------------------------

Op = Literal[">", ">=", "<", "<=", "==", "!="]


class CompareParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Op = Field(default=">", description="How the value compares with the limit.")
    limit: float = Field(default=0.0, description="The limit the value is compared with.")
    deadband: float = Field(
        default=0.0,
        ge=0,
        description="Once true, the value must come back past the limit by this much to clear.",
    )

    @field_validator("limit", "deadband")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("a finite number")
        return value


def compare(value: float, op: str, limit: float) -> bool:
    if op == ">":
        return value > limit
    if op == ">=":
        return value >= limit
    if op == "<":
        return value < limit
    if op == "<=":
        return value <= limit
    if op == "==":
        return abs(value - limit) <= 1e-9 * max(1.0, abs(limit))
    return abs(value - limit) > 1e-9 * max(1.0, abs(limit))


def run_compare(inputs: dict[str, Any], params: CompareParams, context: Context) -> dict[str, Any]:
    values: pd.Series = inputs["value"]
    state = context.state
    active = bool(state.get("active"))
    found = []
    for value in values.to_numpy(dtype=float):
        if not math.isfinite(value):
            found.append(active)
            continue
        now = compare(value, params.op, params.limit)
        if active and not now and params.deadband and params.op in (">", ">=", "<", "<="):
            # Inside the deadband the condition holds (a value hovering at the limit).
            upper = params.op in (">", ">=")
            back = (
                value < params.limit - params.deadband
                if upper
                else value > params.limit + params.deadband
            )
            now = not back
        active = now
        found.append(now)
    state["active"] = active
    return {"condition": pd.Series(found, index=values.index, dtype=bool)}


class BetweenParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float = Field(default=0.0, description="The low end of the range.")
    high: float = Field(default=100.0, description="The high end of the range.")
    inside: bool = Field(default=True, description="True while inside the range; off: outside.")


def run_between(inputs: dict[str, Any], params: BetweenParams, context: Context) -> dict[str, Any]:
    values: pd.Series = inputs["value"]
    within = (values >= params.low) & (values <= params.high)
    found = within if params.inside else ~within & values.notna()
    return {"condition": found.astype(bool)}


def run_changed(inputs: dict[str, Any], params: NoParameters, context: Context) -> dict[str, Any]:
    values: pd.Series = inputs["value"]
    state = context.state
    previous = _number(state.get("previous"))
    samples = _samples(context)
    found = []
    for moment, value in values.items():
        number = _number(value)
        changed = False
        if number is not None and (not samples or moment in samples):
            changed = previous is not None and number != previous
            previous = number
        found.append(changed)
    state["previous"] = previous
    return {"condition": pd.Series(found, index=values.index, dtype=bool)}


class RateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per: Literal["second", "minute", "hour"] = Field(
        default="minute", description="The rate is given in units per second, minute or hour."
    )


SECONDS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}


def run_rate(inputs: dict[str, Any], params: RateParams, context: Context) -> dict[str, Any]:
    values: pd.Series = inputs["value"]
    state = context.state
    last = state.get("last") or [None, None]
    at, previous = _time(last[0]), _number(last[1])
    rate = _number(state.get("rate"))
    samples = _samples(context)
    found = []
    for moment, value in values.items():
        number = _number(value)
        if number is not None and (not samples or moment in samples):
            if at is not None and previous is not None and moment > at:
                rate = (number - previous) / (moment - at).total_seconds() * SECONDS[params.per]
            at, previous = moment, number
        found.append(np.nan if rate is None else rate)
    state["last"] = [_iso(at), previous]
    state["rate"] = rate
    return {"rate": pd.Series(found, index=values.index, dtype=float)}


class DeviationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    absolute: bool = Field(default=True, description="On: how far apart, whatever the side.")


def run_deviation(
    inputs: dict[str, Any], params: DeviationParams, context: Context
) -> dict[str, Any]:
    gap = inputs["value"] - inputs["setpoint"]
    return {"deviation": gap.abs() if params.absolute else gap}


def run_and(inputs: dict[str, Any], params: NoParameters, context: Context) -> dict[str, Any]:
    parts = inputs["conditions"]
    found = pd.Series(True, index=_index(context), dtype=bool)
    for part in parts:
        found &= part.astype(bool)
    return {"condition": found}


def run_or(inputs: dict[str, Any], params: NoParameters, context: Context) -> dict[str, Any]:
    parts = inputs["conditions"]
    found = pd.Series(False, index=_index(context), dtype=bool)
    for part in parts:
        found |= part.astype(bool)
    return {"condition": found}


def run_not(inputs: dict[str, Any], params: NoParameters, context: Context) -> dict[str, Any]:
    return {"condition": ~inputs["condition"].astype(bool)}


# Persistence -----------------------------------------------------------------------------


class ForParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seconds: float = Field(
        default=0.0, ge=0, le=30 * 24 * 3600, description="True for at least this many seconds."
    )
    points: int = Field(
        default=0,
        ge=0,
        le=1000,
        description="And on at least this many values in a row (one per run for an app series).",
    )


def run_for(inputs: dict[str, Any], params: ForParams, context: Context) -> dict[str, Any]:
    condition: pd.Series = inputs["condition"]
    state = context.state
    since = _time(state.get("since"))
    points = int(state.get("points") or 0)
    samples = _samples(context)
    found = []
    for moment, value in condition.items():
        if bool(value):
            since = since or moment
            if not samples or moment in samples:
                points += 1
            held = (moment - since).total_seconds() >= params.seconds
            found.append(held and points >= params.points)
        else:
            since, points = None, 0
            found.append(False)
    state["since"], state["points"] = _iso(since), points
    return {"condition": pd.Series(found, index=condition.index, dtype=bool)}


class TimesParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=3, ge=1, le=100, description="How many times it became true.")
    minutes: int = Field(
        default=60, ge=1, le=7 * 24 * 60, description="Within this many minutes, the latest."
    )


def run_times(inputs: dict[str, Any], params: TimesParams, context: Context) -> dict[str, Any]:
    condition: pd.Series = inputs["condition"]
    state = context.state
    window = pd.Timedelta(minutes=params.minutes)
    edges = [moment for moment in (_time(item) for item in state.get("edges") or []) if moment]
    previous = bool(state.get("previous"))
    found = []
    for moment, value in condition.items():
        value = bool(value)
        if value and not previous:
            edges.append(moment)
        previous = value
        edges = [item for item in edges if item > moment - window]
        found.append(len(edges) >= params.count)
    state["edges"] = [_iso(item) for item in edges[-MAX_HITS:]]
    state["previous"] = previous
    return {"condition": pd.Series(found, index=condition.index, dtype=bool)}


# Python ----------------------------------------------------------------------------------


class PythonParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        default=(
            "def check(inputs):\n"
            "    # inputs.<name>: the last value of each block wired here\n"
            '    return False, ""\n'
        ),
        max_length=20000,
        description="A function check(inputs) that answers (true or false, a sentence).",
    )


def run_python(inputs: dict[str, Any], params: PythonParams, context: Context) -> dict[str, Any]:
    index = _index(context)
    state = context.state
    names = (context.extra.get("names") or {}).get(context.node_id) or []
    values = inputs.get("values") or []
    given: dict[str, Any] = {}
    for name, series in zip(names, values, strict=False):
        if isinstance(series, pd.Series) and len(series.dropna()):
            last = series.dropna().iloc[-1]
            given[name] = bool(last) if series.dtype == bool else float(last)
        else:
            given[name] = None
    last_run = _time(state.get("ran_at"))
    now = index[-1]
    answer = state.get("answer")
    found = [bool(answer)] * len(index)
    if last_run is None or (now - last_run).total_seconds() >= PYTHON_EVERY_SECONDS:
        runner: Callable | None = context.extra.get("python")
        if runner is None:
            return {"condition": NoData(t("Python rules do not run here."), context.node_id)}
        state["ran_at"] = _iso(now)
        try:
            answer, message = runner(context.node_id, params.code, given)
        except Exception as exc:  # noqa: BLE001 - the person's code; the alarm says why
            state["error"] = str(exc)[:300]
            if state.get("answer") is None:
                return {"condition": NoData(state["error"], context.node_id)}
        else:
            state.update(answer=bool(answer), message=str(message or "")[:300], error="")
        found[-1] = bool(state.get("answer"))
    elif answer is None:
        return {"condition": NoData(t("The Python block has not answered yet."), context.node_id)}
    if state.get("message"):
        context.extra.setdefault("messages", {})[context.node_id] = state["message"]
    return {"condition": pd.Series(found, index=index, dtype=bool)}


# Raise an alarm --------------------------------------------------------------------------


class RaiseParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clear_after_seconds: float = Field(
        default=0.0,
        ge=0,
        le=24 * 3600,
        description="The condition must stay false this many seconds before the alarm clears.",
    )
    enable_delay_seconds: float = Field(
        default=0.0,
        ge=0,
        le=24 * 3600,
        description="With an Enabled when input: the alarm is judged only once it held this long.",
    )


def run_raise(inputs: dict[str, Any], params: RaiseParams, context: Context) -> dict[str, Any]:
    condition = inputs.get("condition")
    state = context.state
    if condition is None or isinstance(condition, NoData):
        context.extra["unknown"] = (
            condition.reason if isinstance(condition, NoData) else t("Nothing is wired.")
        )
        return {}
    active = bool(state.get("active"))
    clearing = _time(state.get("clear_since"))
    transitions = context.extra.setdefault("transitions", [])
    # State-based alarming (ISA-18.2 designed suppression): with a permissive wired to Enabled
    # when, the alarm is judged only while it holds (and, with a delay, once it held that long).
    # A permissive that cannot be judged leaves the alarm enabled: a bad signal never hides one.
    enabled = inputs.get("enabled")
    allowed = None
    if enabled is not None and not isinstance(enabled, NoData) and len(condition):
        allowed = enabled.reindex(condition.index, method="ffill").fillna(True).astype(bool)
    since = _time(state.get("enabled_since"))
    suppressed = False
    for moment, value in condition.items():
        if allowed is not None:
            if not bool(allowed.get(moment, True)):
                since = None
            else:
                since = since or moment
            suppressed = since is None or (
                (moment - since).total_seconds() < params.enable_delay_seconds
            )
            if suppressed:
                if active:
                    active, clearing = False, None
                    transitions.append(("cleared", moment))
                continue
        if bool(value):
            clearing = None
            if not active:
                active = True
                transitions.append(("raised", moment))
        elif active:
            clearing = clearing or moment
            if (moment - clearing).total_seconds() >= params.clear_after_seconds:
                active, clearing = False, None
                transitions.append(("cleared", moment))
    state["active"], state["clear_since"] = active, _iso(clearing)
    state["enabled_since"] = _iso(since) if allowed is not None else None
    state["suppressed"] = suppressed
    if suppressed:
        context.extra.setdefault("messages", {})[context.node_id] = t(
            "Suppressed by design: its permissive does not hold."
        )
    elif isinstance(enabled, NoData):
        context.extra.setdefault("messages", {})[context.node_id] = t(
            "Its permissive cannot be judged ({reason}): the alarm stays enabled.",
            reason=enabled.reason,
        )
    return {}


# The library -----------------------------------------------------------------------------


def _docs(summary: str, description: str, reading: str) -> BlockDocs:
    return BlockDocs(summary=summary, description=description, reading=reading)


SERIES = "series"
CONDITION = "intervals"

SPECS: list[tuple[BlockSpec, Callable]] = [
    (
        BlockSpec(
            VALUE_BLOCK,
            "1.0",
            LIBRARY,
            "Value",
            _docs(
                "A value of the plant or of an app: a signal, or a series an app computed.",
                "Reads one signal on each target of the rule: a fixed signal, the asset's "
                "signal with a role (pv, sp), or an app's series about the asset written with "
                "{asset} (app-linkcraft:{asset}.valve_health.health). Held between samples.",
                "The value as the plant or the app wrote it; no value yet leaves the rule unknown.",
            ),
            outputs=(outport("value", SERIES, "Value", "The value, held between its samples."),),
            parameters=ValueParams,
            group="Inputs",
        ),
        run_value,
    ),
    (
        BlockSpec(
            "alarm.event_open",
            "1.0",
            LIBRARY,
            "Event open",
            _docs(
                "Whether an app reports a condition open now, such as a signal without data.",
                "True while a condition of these kinds is open about the target: started by "
                "the app and not ended yet (a source down, a signal without data, a loop "
                "critical). An event without start and end is true at its moment only.",
                "True while open; pair it with For at least to say how long (open over 24 h).",
            ),
            outputs=(outport("open", CONDITION, "Open", "True while a condition is open."),),
            parameters=EventParams,
            group="Inputs",
        ),
        run_event_open,
    ),
    (
        BlockSpec(
            "alarm.event_count",
            "1.0",
            LIBRARY,
            "Count events",
            _docs(
                "How many events of these kinds came about the target in a recent window.",
                "Counts the events of these kinds about the target over the last minutes "
                "(a run failed, a finding opened). The end of a condition is not counted.",
                "A number of events; compare it with how many are too many (at least 3).",
            ),
            outputs=(outport("count", SERIES, "Count", "Events in the window."),),
            parameters=CountParams,
            group="Inputs",
        ),
        run_event_count,
    ),
    (
        BlockSpec(
            "alarm.compare",
            "1.0",
            LIBRARY,
            "Compare",
            _docs(
                "Whether a value is above, below or equal to a limit, with a deadband.",
                "Compares the value with the limit at every moment. With a deadband, once "
                "true it stays true until the value comes back past the limit by the deadband, "
                "so a value hovering at the limit does not chatter.",
                "True while the comparison holds (with the deadband once it held).",
            ),
            inputs=(inport("value", SERIES, "Value", "The value compared with the limit."),),
            outputs=(outport("condition", CONDITION, "Condition", "True while it holds."),),
            parameters=CompareParams,
            group="Logic",
        ),
        run_compare,
    ),
    (
        BlockSpec(
            "alarm.between",
            "1.0",
            LIBRARY,
            "Between",
            _docs(
                "Whether a value is inside, or outside, a range from low to high.",
                "True while the value is within the range, both ends included; with inside "
                "off, true while it is outside. A value not known yet is outside nothing.",
                "True while inside (or outside) the range.",
            ),
            inputs=(inport("value", SERIES, "Value", "The value checked against the range."),),
            outputs=(outport("condition", CONDITION, "Condition", "True while it holds."),),
            parameters=BetweenParams,
            group="Logic",
        ),
        run_between,
    ),
    (
        BlockSpec(
            "alarm.changed",
            "1.0",
            LIBRARY,
            "Changed",
            _docs(
                "Whether a value changed at its latest sample, such as a mode or a setpoint.",
                "True at each sample whose value differs from the one before it, false "
                "otherwise. Pair it with Times in a window for a value that changes too often.",
                "True at the moment of a change.",
            ),
            inputs=(inport("value", SERIES, "Value", "The value watched for changes."),),
            outputs=(outport("condition", CONDITION, "Changed", "True when it changed."),),
            group="Logic",
        ),
        run_changed,
    ),
    (
        BlockSpec(
            "alarm.rate",
            "1.0",
            LIBRARY,
            "Rate of change",
            _docs(
                "How fast a value is changing, per second, minute or hour.",
                "The change between two samples divided by the time between them, held until "
                "the next sample. Compare it with a limit to alarm on a value rising or "
                "falling too fast, before it reaches its limit.",
                "Units per second, minute or hour; negative when falling.",
            ),
            inputs=(inport("value", SERIES, "Value", "The value whose change is measured."),),
            outputs=(outport("rate", SERIES, "Rate", "The change per unit of time."),),
            parameters=RateParams,
            group="Logic",
        ),
        run_rate,
    ),
    (
        BlockSpec(
            "alarm.deviation",
            "1.0",
            LIBRARY,
            "Deviation",
            _docs(
                "How far a value is from its setpoint, or from any other value.",
                "The value minus the setpoint at every moment, or how far apart they are "
                "whatever the side. Compare it with a limit to alarm on a loop far from its "
                "setpoint.",
                "In the value's unit; zero when on the setpoint.",
            ),
            inputs=(
                inport("value", SERIES, "Value", "The measured value (the process variable)."),
                inport("setpoint", SERIES, "Setpoint", "What the value should be."),
            ),
            outputs=(outport("deviation", SERIES, "Deviation", "Value minus setpoint."),),
            parameters=DeviationParams,
            group="Logic",
        ),
        run_deviation,
    ),
    (
        BlockSpec(
            "alarm.and",
            "1.0",
            LIBRARY,
            "And",
            _docs(
                "True while every condition wired to it is true.",
                "Joins conditions, even about different assets (health of one loop and "
                "oscillation on another): true only at the moments when all of them are true.",
                "True while all are true.",
            ),
            inputs=(
                inport(
                    "conditions", CONDITION, "Conditions", "The conditions joined.", multiple=True
                ),
            ),
            outputs=(outport("condition", CONDITION, "Condition", "True while all are true."),),
            group="Logic",
        ),
        run_and,
    ),
    (
        BlockSpec(
            "alarm.or",
            "1.0",
            LIBRARY,
            "Or",
            _docs(
                "True while any condition wired to it is true.",
                "Joins conditions: true at the moments when at least one of them is true. "
                "Use it for several ways the same problem shows.",
                "True while one or more is true.",
            ),
            inputs=(
                inport(
                    "conditions", CONDITION, "Conditions", "The conditions joined.", multiple=True
                ),
            ),
            outputs=(outport("condition", CONDITION, "Condition", "True while any is true."),),
            group="Logic",
        ),
        run_or,
    ),
    (
        BlockSpec(
            "alarm.not",
            "1.0",
            LIBRARY,
            "Not",
            _docs(
                "True while the condition wired to it is false.",
                "Turns a condition around: true when it is false and false when it is true. "
                "Use it for a value that should be there and is not.",
                "The opposite of its input.",
            ),
            inputs=(inport("condition", CONDITION, "Condition", "The condition turned around."),),
            outputs=(outport("condition", CONDITION, "Condition", "The opposite."),),
            group="Logic",
        ),
        run_not,
    ),
    (
        BlockSpec(
            "alarm.for",
            "1.0",
            LIBRARY,
            "For at least",
            _docs(
                "True once a condition has held for a time, or for a number of values in a row.",
                "Waits before passing a condition on: it must stay true for the seconds given "
                "and over the points given (five runs in a row of an app's series). It goes "
                "false as soon as the condition does.",
                "True once the condition held long enough.",
            ),
            inputs=(inport("condition", CONDITION, "Condition", "The condition that must hold."),),
            outputs=(outport("condition", CONDITION, "Condition", "True once it held."),),
            parameters=ForParams,
            group="Persistence",
        ),
        run_for,
    ),
    (
        BlockSpec(
            "alarm.times",
            "1.0",
            LIBRARY,
            "Times in a window",
            _docs(
                "True when a condition became true a number of times within a window.",
                "Counts each time the condition turns true and keeps those within the last "
                "minutes; true while there are at least the count given. Use it for a problem "
                "that comes and goes.",
                "True while the count in the window is reached.",
            ),
            inputs=(inport("condition", CONDITION, "Condition", "The condition counted."),),
            outputs=(outport("condition", CONDITION, "Condition", "True while reached."),),
            parameters=TimesParams,
            group="Persistence",
        ),
        run_times,
    ),
    (
        BlockSpec(
            PYTHON_BLOCK,
            "1.0",
            LIBRARY,
            "Python",
            _docs(
                "A short Python function that decides from the values wired to it.",
                "check(inputs) receives the last value of each block wired to it, by that "
                "block's label (inputs.health), and answers true or false and a sentence. It "
                "runs isolated, at most once a minute; only administrators write it.",
                "True while the function says so; its sentence goes with the alarm.",
            ),
            inputs=(
                inport(
                    "values",
                    (SERIES, CONDITION),
                    "Inputs",
                    "The values and conditions the function reads.",
                    multiple=True,
                    required=False,
                ),
            ),
            outputs=(outport("condition", CONDITION, "Condition", "The function's answer."),),
            parameters=PythonParams,
            group="Logic",
        ),
        run_python,
    ),
    (
        BlockSpec(
            ALARM_BLOCK,
            "1.0",
            LIBRARY,
            "Raise an alarm",
            _docs(
                "Raises the rule's alarm while the condition wired to it is true.",
                "The rule's one output. The alarm is raised when the condition turns true and "
                "clears when it has been false for the seconds given. When the condition cannot "
                "be judged (no data yet), the alarm keeps its state and says why.",
                "Raised while true; cleared after the condition stays false long enough.",
            ),
            inputs=(
                inport("condition", CONDITION, "Condition", "When the alarm is raised."),
                inport(
                    "enabled",
                    CONDITION,
                    "Enabled when",
                    "A permissive: while it is false the alarm is suppressed by design (a low "
                    "flow alarm only while the pump runs). Unknown leaves the alarm enabled.",
                    required=False,
                ),
            ),
            parameters=RaiseParams,
            runs_on_missing=True,
            group="Output",
        ),
        run_raise,
    ),
]

CATALOG: dict[str, Block] = {spec.block_id: Block(spec, run) for spec, run in SPECS}


# A rule's diagram -------------------------------------------------------------------------


def plan_of(diagram: dict[str, Any]) -> Plan:
    return _plan(json.dumps(diagram, sort_keys=True))


@lru_cache(maxsize=512)
def _plan(text: str) -> Plan:
    return compile_diagram(
        json.loads(text), CATALOG, sinks=lambda block: block.spec.block_id == ALARM_BLOCK
    )


def check(diagram: dict[str, Any]) -> Plan:
    """The diagram checked as a rule: valid, with exactly one Raise an alarm."""

    plan = plan_of(diagram)
    raises = [
        node["id"]
        for node in diagram.get("nodes") or []
        if isinstance(node, dict) and node.get("block") == ALARM_BLOCK
    ]
    if plan.valid and len(raises) != 1:
        plan.errors.append(t("A rule has exactly one Raise an alarm block."))
    return plan


def nodes(diagram: dict[str, Any], block: str | tuple[str, ...]) -> list[dict[str, Any]]:
    blocks = (block,) if isinstance(block, str) else block
    return [node for node in diagram.get("nodes") or [] if node.get("block") in blocks]


def relative(diagram: dict[str, Any]) -> bool:
    """Whether the diagram reads anything of "this asset" or "this execution"."""

    for node in nodes(diagram, VALUE_BLOCK):
        params = node.get("parameters") or {}
        if params.get("role") or ASSET in str(params.get("signal") or ""):
            return True
    return any(
        (node.get("parameters") or {}).get("about", "subject") == "subject"
        for node in nodes(diagram, EVENT_BLOCKS)
    )
