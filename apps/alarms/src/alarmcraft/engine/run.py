"""One rule's diagram, run on one subject over one stretch of time (Alarms round 11).

The one judging path: the monitor's cycle (a few seconds of new samples and events) and a rule's
**Test** (the last days at once) both call ``run``, so what a person tests is what the plant
will see. ``run`` builds the moments of the stretch (the samples of the subject's values, the
times of its events and the stretch's end), executes the diagram with the blocks' memory from
``state`` and answers the new state, the raises and clears and what to show (the last value,
the Python block's sentence, why it could not be judged).

``Subject`` is what a rule's alarm is about: an asset, a Link execution, or nothing (a rule
whose values are all named, one alarm). ``about`` says whether an event is about it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import Context, execute

from alarmcraft.alarms.blocks import (
    ALARM_BLOCK,
    ASSET,
    CATALOG,
    EVENT_BLOCKS,
    PYTHON_BLOCK,
    VALUE_BLOCK,
    _time,
    nodes,
    plan_of,
)
from alarmcraft.alarms.model import kind_matches
from alarmcraft.i18n import t


@dataclass(frozen=True)
class Subject:
    """What one alarm of a rule is about. ``key``: the asset id, ``execution:<app>:<id>``, or
    "" for a rule with one alarm."""

    key: str
    kind: str  # "asset", "execution" or "none"
    id: str = ""
    asset: dict[str, Any] | None = None
    label: str | None = None
    app: str = ""

    @property
    def asset_id(self) -> str | None:
        return self.id if self.kind == "asset" else None


@dataclass
class Outcome:
    state: dict[str, Any]
    transitions: list[tuple[str, datetime]] = field(default_factory=list)
    value: float | None = None
    unit: str = ""
    signal: str | None = None
    message: str = ""
    unknown: str = ""
    counted: set[int] = field(default_factory=set)
    # What the last event the rule heard said: summary, severity, schedule, owner, run.
    heard: dict[str, Any] = field(default_factory=dict)


def resolver(subject: Subject) -> Callable[[str, str], str]:
    """``resolve(signal, role)``: the signal a value block reads on this subject."""

    def resolve(signal: str, role: str) -> str:
        if role:
            if subject.asset is None:
                raise LookupError(
                    t("The {role} of each asset needs a rule over assets.", role=role)
                )
            found = (subject.asset.get("signals") or {}).get(role)
            if not found:
                raise LookupError(
                    t(
                        "{asset} has no signal with the role {role}.",
                        asset=subject.asset.get("name") or subject.id,
                        role=role,
                    )
                )
            return str(found)
        if ASSET in signal:
            if subject.kind != "asset":
                raise LookupError(t("This asset's values need a rule over assets."))
            return signal.replace(ASSET, subject.id)
        if not signal:
            raise LookupError(t("The value block names no signal."))
        return signal

    return resolve


def signals_of(diagram: dict[str, Any], subject: Subject) -> tuple[set[str], str]:
    """The signals the diagram reads on ``subject``, and why one cannot be found."""

    resolve = resolver(subject)
    found: set[str] = set()
    why = ""
    for node in nodes(diagram, VALUE_BLOCK):
        params = node.get("parameters") or {}
        try:
            found.add(resolve(str(params.get("signal") or ""), str(params.get("role") or "")))
        except LookupError as exc:
            why = why or str(exc)
    return found, why


def about(subject: Subject) -> Callable[[dict[str, Any], str], bool]:
    """``about(event, about)``: whether an event is about the subject (``subject``), any
    (``any``) or about a given ref (``asset:FIC-1002``)."""

    signals = {f"signal:{item}" for item in ((subject.asset or {}).get("signals") or {}).values()}
    own = f"asset:{subject.id}" if subject.kind == "asset" else ""

    def check_one(event: dict[str, Any], given: str) -> bool:
        if given == "any":
            return True
        named = {str(event.get("subject") or ""), *(str(ref) for ref in event.get("refs") or [])}
        if given and given != "subject":
            return given in named
        if subject.kind == "asset":
            return own in named or bool(signals & named)
        if subject.kind == "execution":
            payload = event.get("payload") or {}
            return (
                str(event.get("app") or "") == subject.app
                and str(payload.get("schedule_id") or "") == subject.id
            )
        return False

    return check_one


def _names(diagram: dict[str, Any]) -> dict[str, list[str]]:
    """Each Python block's input names: the labels of the blocks wired to it, in order."""

    labels = {node["id"]: node.get("label") or node["id"] for node in diagram.get("nodes") or []}
    found: dict[str, list[str]] = {}
    for edge in diagram.get("edges") or []:
        target = edge.get("target")
        if any(node["id"] == target for node in nodes(diagram, PYTHON_BLOCK)):
            found.setdefault(target, []).append(str(labels.get(edge.get("source"), "value")))
    return found


def run(
    diagram: dict[str, Any],
    subject: Subject,
    state: dict[str, Any],
    *,
    series: dict[str, pd.Series],
    events: list[dict[str, Any]],
    end: datetime,
    open_now: list[dict[str, Any]] | None = None,
    python: Callable[[str, str, dict[str, Any]], tuple[bool, str]] | None = None,
) -> Outcome:
    """The diagram on ``subject`` after ``state["evaluated_until"]`` up to ``end``."""

    state = dict(state or {})
    plan = plan_of(diagram)
    outcome = Outcome(state)
    if not plan.valid:
        outcome.unknown = " ".join(plan.errors) or t("The rule's diagram is not valid.")
        return outcome
    after = _time(state.get("evaluated_until"))
    stop = pd.Timestamp(end)
    stop = stop.tz_localize("UTC") if stop.tzinfo is None else stop.tz_convert("UTC")
    signals, _ = signals_of(diagram, subject)
    seen = dict(state.get("seen") or {})
    # A sample or an event stamped before the last run (an app writes its run's point when the
    # run ends) still counts, once, as if it came now.
    floor = None if after is None else after + pd.Timedelta(microseconds=1)
    fresh: dict[str, pd.Series] = {}
    moments: set[pd.Timestamp] = set()
    for signal in signals:
        column = series.get(signal)
        if column is None or not len(column):
            continue
        column = column.dropna().sort_index()
        index = pd.DatetimeIndex(column.index)
        index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
        column.index = index
        last = _time(seen.get(signal)) or after
        keep = (index <= stop) if last is None else ((index > last) & (index <= stop))
        column = column[keep]
        if not len(column):
            continue
        seen[signal] = column.index[-1].isoformat()
        if floor is not None:
            column.index = pd.DatetimeIndex([max(moment, floor) for moment in column.index])
        column = column[~column.index.duplicated(keep="last")]
        fresh[signal] = column
        moments.update(column.index)
    state["seen"] = seen
    mine = about(subject)
    window = []
    for event in events:
        at = _time(event.get("at")) or stop
        at = min(max(at, floor) if floor is not None else at, stop)
        window.append({**event, "at": at.isoformat()})
        moments.add(at)
    window.sort(key=lambda item: _time(item["at"]))
    samples = set(moments)
    moments.update(_timers(diagram, state, moments, stop))
    moments.add(stop)
    index = pd.DatetimeIndex(sorted(moments))
    context = Context(
        start=index[0],
        end=stop,
        asset=subject.asset or {},
        states=state.setdefault("nodes", {}),
        extra={
            "index": index,
            "samples": samples,
            "series": fresh,
            "resolve": resolver(subject),
            "events": window,
            "about": mine,
            "open_now": open_now or [],
            "python": python,
            "names": _names(diagram),
            "transitions": [],
        },
    )
    execute(plan, CATALOG, context)
    extra = context.extra
    outcome.transitions = [(kind, moment.to_pydatetime()) for kind, moment in extra["transitions"]]
    shown = extra.get("shown") or {}
    if shown:
        value, unit, signal = next(iter(shown.values()))
        outcome.value, outcome.unit, outcome.signal = value, unit, signal
    outcome.message = " ".join((extra.get("messages") or {}).values())[:300]
    outcome.unknown = str(extra.get("unknown") or "")
    matched = [event for event in window if _counts(diagram, event, mine)]
    outcome.counted = {int(event["id"]) for event in matched if event.get("id") is not None}
    if matched:
        outcome.heard = heard(matched[-1])
    raise_node = nodes(diagram, ALARM_BLOCK)
    raised = (state["nodes"].get(raise_node[0]["id"]) or {}) if raise_node else {}
    state["active"] = bool(raised.get("active"))
    # Suppressed by design: the rule's permissive does not hold (``alarm.raise`` Enabled when).
    state["suppressed"] = bool(raised.get("suppressed"))
    state["evaluated_until"] = stop.isoformat()
    return outcome


# A stretch with more moments than this is dense enough: no timer moments are added.
MAX_TIMER_BASE = 20000


def _timers(
    diagram: dict[str, Any], state: dict[str, Any], moments: set[pd.Timestamp], stop: pd.Timestamp
) -> set[pd.Timestamp]:
    """The moments a timer elapses between samples and events (a condition true "for 1 h",
    "clear after 10 min", a count's window ending), so a Test over days and a quiet stretch
    judge them when they happen, not at the next sample."""

    spans: set[pd.Timedelta] = set()
    for node in diagram.get("nodes") or []:
        params = node.get("parameters") or {}
        block = node.get("block")
        if block == "alarm.for" and params.get("seconds"):
            spans.add(pd.Timedelta(seconds=float(params["seconds"])))
        elif block == ALARM_BLOCK and params.get("clear_after_seconds"):
            spans.add(pd.Timedelta(seconds=float(params["clear_after_seconds"])))
        elif block == "alarm.event_count":
            spans.add(pd.Timedelta(minutes=float(params.get("window_minutes") or 60)))
        elif block == "alarm.times":
            spans.add(pd.Timedelta(minutes=float(params.get("minutes") or 60)))
    if not spans:
        return set()
    starts = set(moments) if len(moments) <= MAX_TIMER_BASE else set()
    for memory in (state.get("nodes") or {}).values():
        for key in ("since", "clear_since"):
            found = _time((memory or {}).get(key))
            if found is not None:
                starts.add(found)
        for key in ("hits", "edges"):
            starts.update(
                moment
                for moment in (_time(item) for item in (memory or {}).get(key) or [])
                if moment
            )
    after = _time(state.get("evaluated_until"))
    found: set[pd.Timestamp] = set()
    for start in starts:
        for span in spans:
            for extra in spans:
                for moment in (start + span, start + span + extra):
                    if moment < stop and (after is None or moment > after):
                        found.add(moment)
    return found


def _counts(diagram: dict[str, Any], event: dict[str, Any], mine: Callable) -> bool:
    for node in nodes(diagram, EVENT_BLOCKS):
        params = node.get("parameters") or {}
        severities = list(params.get("severities") or [])
        if (
            kind_matches(list(params.get("kinds") or []), str(event.get("kind") or ""))
            and mine(event, str(params.get("about") or "subject"))
            and (not severities or str(event.get("severity") or "") in severities)
        ):
            return True
    return False


def heard(event: dict[str, Any]) -> dict[str, Any]:
    """What an alarm keeps of the last event its rule heard."""

    payload = event.get("payload") or {}
    run_ref = next((ref for ref in event.get("refs") or [] if str(ref).startswith("run:")), None)
    return {
        "last_summary": str(event.get("summary") or "")[:300],
        "severity": str(event.get("severity") or "") or None,
        "schedule_id": str(payload.get("schedule_id") or "") or None,
        "responsible": str(payload.get("owner") or "") or None,
        "run": run_ref,
    }


def occurrences(transitions: list[tuple[str, datetime]], end: datetime) -> list[dict[str, Any]]:
    """Raises and clears as occurrences (a Test's answer): start, end (None while open)."""

    found: list[dict[str, Any]] = []
    for kind, moment in transitions:
        if kind == "raised":
            found.append({"start": moment.isoformat(), "end": None})
        elif found and found[-1]["end"] is None:
            found[-1]["end"] = moment.isoformat()
    return found
