"""Rules: list, create, change, turn off and delete them, see the alarms each one makes, test a
rule on the last days of values and events before saving it, and start a rule from an event
that came in. The editors check a rule's diagram (``/rules/check``) and turn the Simple form into
its diagram and sentence (``/rules/simple``). Only administrators write or change a Python block's code; anyone who
edits rules may test and use it."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.auth import User
from plantcraft_sdk.contributes import StartIn, StartOut
from pydantic import BaseModel, ConfigDict, Field

from alarmcraft.alarms import blocks
from alarmcraft.alarms.model import CREATES, PRIORITIES, kind_matches
from alarmcraft.alarms.records import Conflict
from alarmcraft.alarms.rules import RuleDraft, from_legacy
from alarmcraft.alarms.simple import SimpleLogic, to_diagram
from alarmcraft.api.deps import CurrentUser, EditorUser, EditorView, RuntimeDep, guarded
from alarmcraft.api.routers.alarms import mark_mine, summary, window_of
from alarmcraft.api.runtime import Runtime
from alarmcraft.api.scope import seen
from alarmcraft.engine import python as python_block
from alarmcraft.engine import run as engine
from alarmcraft.engine import scope
from alarmcraft.i18n import t
from alarmcraft.monitor.service import judge
from alarmcraft.monitor.sync import draft_of

router = APIRouter(prefix="/api", tags=["rules"])
MAX_TRY_POINTS = 5000
# A Test reads at most this many of the rule's subjects.
MAX_TRY_SUBJECTS = 20
MAX_TRY = timedelta(days=7)
EDITORS = {"simple": "Simple", "blocks": "Blocks", "python": "Python"}
CLOSING = ((".opened", ".closed"), (".started", ".ended"))


class RuleChange(RuleDraft):
    model_config = ConfigDict(extra="forbid")

    base_updated_at: str | None = Field(default=None, max_length=60)


class Enabled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class TryRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: RuleDraft
    window: str = Field(default="24h", max_length=10)
    # The rule being changed, when it is saved already (its code may be tested by anyone).
    rule_id: str | None = Field(default=None, max_length=63)


class CheckDiagram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagram: dict[str, Any]


class SignalRule(BaseModel):
    """One signal's limit, as the assistant's "Help me create an alarm" proposes it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    signal_id: str = Field(min_length=1, max_length=300)
    kind: str = Field(pattern="^(high_high|high|low|low_low|no_data)$")
    limit: float | None = None
    unit: str = Field(default="", max_length=40)
    deadband: float = Field(default=0.0, ge=0)
    on_delay_seconds: float = Field(default=0.0, ge=0)
    priority: str = "medium"
    cause: str = Field(default="", max_length=2000)
    consequence: str = Field(default="", max_length=2000)
    action: str = Field(default="", max_length=2000)


class SimpleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simple: SimpleLogic


def _where(rt: Runtime, rule: dict[str, Any]) -> str:
    """Where the rule applies, in words: "FIC-1001, under Unit 100", "any asset"."""

    assets = rt.tree.assets()
    where = rule.get("where") or {}

    def name(asset_id: str) -> str:
        return str((assets.get(asset_id) or {}).get("name") or asset_id)

    if where.get("anywhere"):
        return t("any asset the events name")
    places = [name(item) for item in where.get("assets") or []]
    places += [t("under {branch}", branch=name(item)) for item in where.get("under") or []]
    places += [t("every {type}", type=item) for item in where.get("types") or []]
    places += [
        t("execution {execution}", execution=item.partition(":")[2])
        for item in where.get("executions") or []
    ]
    found = ", ".join(places) if places else t("the values it names")
    if where.get("per") == "rule" and places:
        found += " " + t("(one alarm)")
    elif where.get("per") == "execution":
        found += " " + t("(one alarm per execution)")
    return found


def rule_row(rt: Runtime, rule: dict[str, Any], alarms: list[dict[str, Any]]) -> dict[str, Any]:
    """A rule as the pages show it, with how many alarms it has and how many are active."""

    now = rt.clock()
    rows = [summary(rt, alarm) for alarm in alarms]
    notify = rule.get("notify") or {}
    draft = draft_of(rule)
    return {
        **rule,
        "editor_label": EDITORS.get(rule.get("editor") or "", ""),
        "priority_label": PRIORITIES.get(rule.get("priority") or "", ""),
        "creates_label": CREATES.get(rule.get("creates") or "alarm", ""),
        "where_words": _where(rt, rule),
        "sentence": draft.sentence() if draft is not None else "",
        "valid": draft is not None,
        "alarms": len(rows),
        "active": sum(1 for row in rows if row["active"]),
        "unacked": sum(1 for row in rows if row["status"] in ("unacked", "rtn_unacked")),
        "unknown": sum(1 for row in rows if row.get("known") is False),
        "notifies": bool(notify.get("enabled", True)),
        "recipients": list(notify.get("recipients") or []),
        "at": now.isoformat(),
    }


def rule_or_404(rt: Runtime, rule_id: str) -> dict[str, Any]:
    found = rt.rules.get(rule_id) if len(rule_id) <= 63 else None
    if found is None:
        raise HTTPException(404, t("Rule not found."))
    return found


def _changed(rt: Runtime, rule: dict[str, Any], by: str) -> None:
    rt.sync.sync(rule, by=by)
    rt.monitor.publish_schedules()


def guard_code(draft: RuleDraft, user: User, before: dict[str, Any] | None) -> None:
    """Only administrators write a Python block's code (any new or changed code); the code
    must pass the sandbox's check."""

    code = draft.code()
    saved = draft_of(before) if before is not None else None
    old = saved.code() if saved is not None else []
    if code and sorted(code) != sorted(old) and not user.is_admin:
        raise HTTPException(403, t("Only administrators write or change Python in a rule."))
    for text in code:
        problems = python_block.problems(text)
        if problems:
            raise HTTPException(422, t("The Python block: {why}", why="; ".join(problems[:3])))


@router.get("/rules")
def list_rules(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    alarms = seen(rt.asset_scope(user), rt.alarms.list())
    by_rule: dict[str, list[dict[str, Any]]] = {}
    for alarm in alarms:
        by_rule.setdefault(alarm.get("rule_id") or "", []).append(alarm)
    return [rule_row(rt, rule, by_rule.get(rule["rule_id"], [])) for rule in rt.rules.list()]


@router.post("/rules/check")
def check_diagram(body: CheckDiagram, _user: CurrentUser) -> dict[str, Any]:
    """A diagram checked as a rule while it is drawn (the editor marks the blocks in error)."""

    report = blocks.check(body.diagram).report()
    for node in blocks.nodes(body.diagram, blocks.PYTHON_BLOCK):
        problems = python_block.problems(str((node.get("parameters") or {}).get("code") or ""))
        if problems:
            report["valid"] = False
            report["errors"] = [*report.get("errors", []), *problems[:3]]
            report.setdefault("node_errors", {})[node["id"]] = problems[:3]
    return report


@router.post("/rules/simple")
def simple_rule(body: SimpleBody, _user: CurrentUser) -> dict[str, Any]:
    """The Simple form's diagram and sentence (to open it in Blocks, or to read it back)."""

    return {"diagram": to_diagram(body.simple), "sentence": body.simple.sentence()}


@router.post("/rules", status_code=201)
def create_rule(draft: RuleDraft, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    guard_code(draft, user, None)
    if not draft.owner:
        draft.owner = f"user:{user.username}"
    taken = {alarm["alarm_id"] for alarm in rt.alarms.list()}
    rule = rt.rules.create(draft.config(), by=user.username, taken=taken)
    rt.audit(user, "rule.created", rule["rule_id"], {"name": rule["name"]})
    _changed(rt, rule, user.username)
    return get_rule(rule["rule_id"], rt, user)


@router.post("/rules/from-signal", status_code=201)
def create_signal_rule(body: SignalRule, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """A Simple rule on one signal's limit (or its silence), from the assistant's proposal."""

    if body.kind != "no_data" and body.limit is None:
        raise HTTPException(422, t("Give the limit."))
    draft = RuleDraft.model_validate(from_legacy(body.model_dump()))
    return create_rule(draft, rt, user)


# A new plant's first rules, one pair per unit, switched off until someone reviews them.
STARTER_RULES = (
    {
        "kind": "verdict",
        "name": "{unit}: loop in poor shape",
        "priority": "medium",
        "cause": "Analytics found a loop of this unit performing badly.",
        "action": "Open the loop in Analytics and read its likely causes.",
    },
    {
        "kind": "no_data",
        "name": "{unit}: signal without data",
        "priority": "low",
        "on_delay_seconds": 600,
        "cause": "The Historian has no new value of a signal of this unit.",
        "action": "Check the signal's source and its instrument.",
    },
)


@router.post("/start/draft-rules")
def start_draft_rules(body: StartIn, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """A new plant's first step here (``[[contributes.start]]``, sent by PlantCraft once an
    import is applied): for each of its units, a rule for a loop in poor shape and one for a
    signal without data, both switched off for a person to review. A rule of that name is kept."""

    names = {asset.id: asset.name or asset.id for asset in body.assets}
    taken = {rule["name"] for rule in rt.rules.list()}
    created = kept = 0
    for unit in body.units:
        for starter in STARTER_RULES:
            name = t(starter["name"], unit=names.get(unit, unit))[:120]
            if name in taken:
                kept += 1
                continue
            words = {"cause": t(starter["cause"]), "action": t(starter["action"])}
            legacy = {**starter, **words, "name": name, "enabled": False, "under": [unit]}
            draft = RuleDraft.model_validate(from_legacy(legacy))
            create_rule(draft, rt, user)
            taken.add(name)
            created += 1
    summary = t(
        "{created} alarm rules were drafted for {units} units, switched off: review and switch "
        "them on in Rules.",
        created=created,
        units=len(body.units),
    )
    if kept:
        summary += " " + t("{count} were there already.", count=kept)
    counts = {"created": created, "kept": kept}
    return StartOut(summary=summary, counts=counts, open="/alarm/rules").model_dump()


def _subjects(rt: Runtime, rule: RuleDraft) -> list[engine.Subject]:
    """The subjects a Test reads: the rule's, one by one for a rule with one alarm over many
    assets, and for a rule ``anywhere`` the assets its events named lately."""

    assets = rt.tree.assets()
    schedules = rt.executions.list()
    if rule.where.anywhere:
        kinds = rule.hears()
        seen: list[str] = []
        for event in rt.incoming.listing(limit=2000):
            if kind_matches(kinds, str(event.get("kind") or "")):
                seen += [item for item in scope.event_assets(event, assets) if item not in seen]
        return [scope.asset_subject(assets, item, single=False) for item in seen]
    if rule.where.per == "rule" and not rule.where.empty:
        each = rule.where.model_copy(update={"per": "asset"})
        return scope.subjects(rule.model_copy(update={"where": each}), assets, schedules)
    return scope.subjects(rule, assets, schedules)


@router.post("/rules/try")
def try_rule(body: TryRule, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """What the rule would have done over the last ``window`` (at most 7 days): its diagram on
    the plant's history (read as the person) and on the events that came in, for up to 20 of
    its subjects. A Python block answers once, for now."""

    span = min(window_of(body.window), MAX_TRY)
    end = rt.clock()
    start = end - span
    rule = body.rule
    before = rt.rules.get(body.rule_id) if body.rule_id else None
    guard_code(rule, user, before)
    subjects = _subjects(rt, rule)
    if not subjects:
        raise HTTPException(422, t("The rule covers no asset now."))
    step = max(1.0, math.ceil(span.total_seconds() / MAX_TRY_POINTS))
    reader = rt.user_reader(user)
    events = rt.incoming.since(start.isoformat())
    wanted: set[str] = set()
    problems: list[str] = []
    tried = subjects[:MAX_TRY_SUBJECTS]
    for subject in tried:
        signals, why = engine.signals_of(rule.diagram, subject)
        wanted |= signals
        if why:
            problems.append(why)
    columns, errors = (
        guarded(lambda: reader.read(sorted(wanted), start, end, step), service=False)
        if wanted
        else ({}, {})
    )
    problems += [detail for detail in errors.values() if detail]
    found: list[dict[str, Any]] = []
    chart: dict[str, Any] = {"t": [], "v": []}
    first_signal = None
    for subject in tried:
        outcome = judge(
            rule,
            subject,
            {"evaluated_until": start.isoformat()},
            series=columns,
            events=events,
            end=end,
            python=python_block.run,
        )
        occurrences = engine.occurrences(outcome.transitions, end)
        found.append(
            {
                "label": subject.label or subject.key or rule.name,
                "subject": subject.key,
                "signal": outcome.signal,
                "count": len(occurrences),
                "occurrences": occurrences[-200:],
                "unknown": outcome.unknown,
                "message": outcome.message,
            }
        )
        if outcome.unknown:
            problems.append(outcome.unknown)
        if first_signal is None and outcome.signal and outcome.signal in columns:
            first_signal = outcome.signal
            clean = columns[first_signal].astype(float).replace([np.inf, -np.inf], np.nan)
            clean = clean.dropna()
            chart = {
                "t": [moment.isoformat() for moment in clean.index],
                "v": [float(value) for value in clean.values],
            }
    found.sort(key=lambda item: (-item["count"], str(item["label"])))
    total = sum(item["count"] for item in found)
    result = _tried(
        rule,
        found,
        total,
        start,
        end,
        span,
        step=step,
        chart=chart,
        signal=first_signal,
        subjects=len(subjects),
        problems=list(dict.fromkeys(problems)),
    )
    result["events"] = len(events)
    return result


def _tried(
    rule: RuleDraft,
    found: list[dict[str, Any]],
    total: int,
    start: datetime,
    end: datetime,
    span: timedelta,
    *,
    step: float,
    chart: dict[str, Any],
    signal: str | None,
    subjects: int,
    problems: list[str],
) -> dict[str, Any]:
    """The answer of Test: how many alarms, and about how many messages the gathering would
    have sent (one per gathering window with a raise)."""

    raises = sorted(
        datetime.fromisoformat(item["start"])
        for row in found
        for item in row["occurrences"]
        if item.get("start")
    )
    gather = timedelta(seconds=rule.notify.group_seconds)
    messages, last = 0, None
    for moment in raises:
        if last is None or moment - last >= gather:
            messages, last = messages + 1, moment
    hours = max(span.total_seconds() / 3600, 1e-9)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": step,
        "count": total,
        "per_hour": round(total / hours, 2),
        "subjects": subjects,
        "tried": len(found),
        "messages": messages if rule.notify.enabled else 0,
        "messages_per_hour": round((messages if rule.notify.enabled else 0) / hours, 2),
        "alarms": found,
        "signal": signal,
        "occurrences": found[0]["occurrences"] if found else [],
        "chart": chart,
        "problems": problems[:5],
    }


@router.get("/rules/from-event/{event_id}")
def rule_from_event(event_id: int, rt: RuntimeDep, _user: EditorView) -> dict[str, Any]:
    """A new Simple rule filled in from an event that came in: its kind and severity, over the
    asset it named (any asset otherwise)."""

    if event_id < 1 or event_id > 2**62:
        raise HTTPException(404, t("Event not found."))
    event = rt.incoming.get(event_id)
    if event is None:
        raise HTTPException(404, t("Event not found."))
    severity = event.get("severity")
    phase = str(event.get("phase") or "instant")
    named = scope.event_assets(event, rt.tree.assets())
    kinds = [event["kind"]]
    # A condition opened by one kind and closed by another (``finding.opened``/``.closed``):
    # the rule hears both, so the end clears it.
    for start, end in CLOSING:
        if phase in ("start", "end") and event["kind"].endswith(start):
            kinds.append(event["kind"].removesuffix(start) + end)
    condition: dict[str, Any] = {
        "input": "event",
        "event": {
            "kinds": kinds,
            "severities": [severity] if severity in ("warning", "critical") else [],
        },
        "test": "open" if phase in ("start", "end") else "count",
    }
    if condition["test"] == "count":
        condition.update(count=1, window_minutes=60)
    return {
        "name": f"{event['kind']}"[:120],
        "creates": "notice",
        "priority": "high" if severity == "critical" else "medium",
        "where": {"assets": named[:1]} if named else {"anywhere": True},
        "editor": "simple",
        "simple": {"conditions": [condition]},
    }


@router.get("/rules/{rule_id}")
def get_rule(rule_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    rule = rule_or_404(rt, rule_id)
    alarms = rt.alarms.of_rule(rule_id)
    rows = mark_mine(rt, [summary(rt, alarm) for alarm in alarms], user.username)
    return {**rule_row(rt, rule, alarms), "alarm_rows": rows}


@router.put("/rules/{rule_id}")
def change_rule(rule_id: str, body: RuleChange, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    before = rule_or_404(rt, rule_id)
    draft = RuleDraft.model_validate(body.model_dump(exclude={"base_updated_at"}))
    if draft.external_id is None:
        # The editors do not send it: an imported rule stays matched to its alarm list.
        draft.external_id = before.get("external_id")
    guard_code(draft, user, before)
    try:
        rule = rt.rules.update(
            rule_id, draft.config(), by=user.username, base_updated_at=body.base_updated_at
        )
    except Conflict as exc:
        raise HTTPException(
            409, t("Someone changed this rule since you opened it; reload it.")
        ) from exc
    rt.audit(user, "rule.changed", rule_id, {"name": draft.name})
    _changed(rt, rule or {}, user.username)
    return get_rule(rule_id, rt, user)


@router.post("/rules/{rule_id}/enabled")
def rule_enabled(rule_id: str, body: Enabled, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """On or off: a rule that is off judges nothing, and its alarms are out of service."""

    rule = rule_or_404(rt, rule_id)
    config = {key: value for key, value in rule.items() if key in RuleDraft.model_fields}
    config["enabled"] = body.enabled
    try:
        draft = RuleDraft.model_validate(config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    changed = rt.rules.update(rule_id, draft.config(), by=user.username)
    rt.audit(user, "rule.enabled" if body.enabled else "rule.disabled", rule_id)
    _changed(rt, changed or rule, user.username)
    return get_rule(rule_id, rt, user)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, rt: RuntimeDep, user: EditorUser) -> None:
    rule = rule_or_404(rt, rule_id)
    rt.sync.remove(rule_id, by=user.username)
    rt.rules.delete(rule_id)
    rt.audit(user, "rule.deleted", rule_id, {"name": rule["name"]})
    rt.monitor.publish_schedules()


@router.get("/rules/{rule_id}/journal")
def rule_journal(
    rule_id: str,
    rt: RuntimeDep,
    user: CurrentUser,
    window: str = Query(default="7d", max_length=10),
) -> list[dict[str, Any]]:
    rule_or_404(rt, rule_id)
    end = rt.clock()
    scope = rt.asset_scope(user)
    ids = {alarm["alarm_id"] for alarm in seen(scope, rt.alarms.of_rule(rule_id))}
    rows = rt.alarms.journal(
        start=(end - window_of(window)).isoformat(), end=end.isoformat(), limit=5000
    )
    return [
        row
        for row in rows
        if row["alarm_id"] in ids
        or (
            scope.everything
            and (row["alarm_id"] == rule_id or row["alarm_id"].startswith(f"{rule_id}--"))
        )
    ][:1000]
