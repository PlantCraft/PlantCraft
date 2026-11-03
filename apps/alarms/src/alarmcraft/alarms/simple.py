"""The Simple form of a rule: up to three conditions joined by and or or, read as a sentence,
written as the rule's diagram (``alarms.blocks``) so it runs like any other.

A condition is a value compared with a limit (above, below, equal, between, outside, changed, did not change: a frozen value)
or an event (open now, or so many times in a window), and how long it must last (for so many
seconds, over so many values in a row: one value per run of an app's series)::

    When FIC-1001 › Link › Health < 50 for 5 values in a row, raise a medium alarm.

``to_diagram`` gives the diagram; ``sentence`` the words; a diagram from the form can later be
opened in Blocks (it is an ordinary diagram), not the other way round.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alarmcraft.alarms.blocks import ALARM_BLOCK, GRADE_BLOCK, VALUE_BLOCK, GradeEntry, _kinds
from alarmcraft.i18n import t

Op = Literal[">", ">=", "<", "<=", "==", "!=", "between", "outside", "changed", "unchanged"]
OP_WORDS = {
    ">": ">",
    ">=": "≥",
    "<": "<",
    "<=": "≤",
    "==": "=",
    "!=": "≠",
}


class SimpleValue(BaseModel):
    """A value as the Explorer gave it: a signal id ({asset} for each asset) or a role."""

    model_config = ConfigDict(extra="forbid")

    signal: str = Field(default="", max_length=320)
    role: str = Field(default="", max_length=40, pattern=r"^([a-z][a-z0-9_]{0,39})?$")
    name: str = Field(default="", max_length=300)
    unit: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def _one(self) -> SimpleValue:
        self.signal, self.role = self.signal.strip(), self.role.strip()
        if bool(self.signal) == bool(self.role):
            raise ValueError(t("choose a value: a signal or a signal role"))
        return self

    def words(self) -> str:
        if self.name:
            return self.name
        return self.signal.replace("{asset}", t("this asset")) if self.signal else self.role


# The suite's apps by the prefix of their event kinds: a rule reads "Analytics run failed", not
# "linkcraft.run.failed".
APP_NAMES = {
    "processcraft": "PlantCraft",
    "linkcraft": "Analytics",
    "histcraft": "Historian",
    "dashcraft": "View",
    "alarmcraft": "Alarms",
    "modelcraft": "Models",
    "doccraft": "Documents",
}


def kind_words(kind: str) -> str:
    """An event kind in words: its app's name, then the rest ("Historian point no data")."""

    app, _, rest = kind.partition(".")
    if not rest:
        return kind
    return f"{APP_NAMES.get(app, app)} {rest.replace('.', ' ').replace('_', ' ')}"


class SimpleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kinds: list[str] = Field(min_length=1, max_length=20)
    severities: list[Literal["warning", "critical"]] = Field(default_factory=list, max_length=2)
    about: str = Field(default="subject", max_length=320)
    name: str = Field(default="", max_length=300)

    @field_validator("kinds")
    @classmethod
    def _valid(cls, value: list[str]) -> list[str]:
        return _kinds(value)

    def words(self) -> str:
        return self.name or ", ".join(kind_words(kind) for kind in self.kinds)


class SimpleGrade(BaseModel):
    """Where the product grade being made comes from: a signal holding its code, or the
    latest event of these kinds, whose payload ``field`` names it."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["value", "event"] = "value"
    value: SimpleValue | None = None
    kinds: list[str] = Field(default_factory=list, max_length=20)
    about: str = Field(default="any", max_length=320)
    field: str = Field(default="grade", min_length=1, max_length=60,
                       pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,59}$")  # fmt: skip
    name: str = Field(default="", max_length=300)

    @field_validator("kinds")
    @classmethod
    def _valid(cls, value: list[str]) -> list[str]:
        return _kinds(value) if value else []

    @model_validator(mode="after")
    def _complete(self) -> SimpleGrade:
        if self.source == "value":
            if self.value is None:
                raise ValueError(t("choose the signal that holds the grade"))
            self.kinds = []
        else:
            if not self.kinds:
                raise ValueError(t("choose the events that name the grade"))
            self.value = None
        return self

    def words(self) -> str:
        if self.source == "value" and self.value is not None:
            return self.value.words()
        what = self.name or ", ".join(kind_words(kind) for kind in self.kinds)
        return t("{events} ({field})", events=what, field=self.field)


class SimpleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: Literal["value", "event"] = "value"
    value: SimpleValue | None = None
    op: Op = ">"
    limit: float | None = None
    high: float | None = None
    deadband: float = Field(default=0.0, ge=0)
    event: SimpleEvent | None = None
    test: Literal["open", "count"] = "open"
    count: int = Field(default=1, ge=1, le=100)
    window_minutes: int = Field(default=60, ge=1, le=7 * 24 * 60)
    for_seconds: float = Field(default=0.0, ge=0, le=30 * 24 * 3600)
    for_points: int = Field(default=0, ge=0, le=1000)
    # Limits by product grade (with the rule's ``grade``): the limit while each grade is made;
    # any other grade, or none known yet, keeps ``limit``.
    grade_limits: list[GradeEntry] = Field(default_factory=list, max_length=100)

    @field_validator("limit", "high", "deadband")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError(t("a finite number"))
        return value

    @model_validator(mode="after")
    def _complete(self) -> SimpleCondition:
        if self.input == "value":
            if self.value is None:
                raise ValueError(t("choose the value"))
            self.event = None
            if self.op in ("between", "outside"):
                if self.limit is None or self.high is None or self.high < self.limit:
                    raise ValueError(t("a range needs its low and high ends"))
            elif self.op not in ("changed", "unchanged") and self.limit is None:
                raise ValueError(t("a comparison needs its limit"))
            if self.grade_limits and self.op in ("between", "outside", "changed", "unchanged"):
                raise ValueError(t("limits by grade are for a value compared with one limit"))
            grades = [item.grade for item in self.grade_limits]
            if len(set(grades)) != len(grades):
                raise ValueError(t("each grade once in a condition"))
        else:
            if self.event is None:
                raise ValueError(t("choose the event"))
            self.value = None
            self.grade_limits = []
        return self

    def words(self) -> str:
        if self.input == "event" and self.event is not None:
            what = self.event.words()
            if self.test == "count":
                found = t(
                    "{event} happened once in {window}"
                    if self.count == 1
                    else "{event} happened {count} times in {window}",
                    event=what,
                    count=self.count,
                    window=span(self.window_minutes),
                )
            else:
                found = t("{event} is open", event=what)
        else:
            assert self.value is not None
            what = self.value.words()
            unit = f" {self.value.unit}" if self.value.unit else ""
            if self.op == "changed":
                found = t("{value} changed", value=what)
            elif self.op == "unchanged":
                found = t("{value} did not change", value=what)
            elif self.op in ("between", "outside"):
                found = t(
                    "{value} is between {low} and {high}{unit}"
                    if self.op == "between"
                    else "{value} is outside {low} to {high}{unit}",
                    value=what,
                    low=f"{self.limit:g}",
                    high=f"{self.high:g}",
                    unit=unit,
                )
            else:
                found = f"{what} {OP_WORDS[self.op]} {self.limit:g}{unit}"
                if self.grade_limits:
                    found += t(
                        " ({grades} by grade)",
                        grades=", ".join(
                            f"{item.grade}: {item.limit:g}" for item in self.grade_limits
                        ),
                    )
        lasting = []
        if self.for_seconds:
            lasting.append(t("for {time}", time=seconds_words(self.for_seconds)))
        if self.for_points:
            lasting.append(t("for {count} values in a row", count=self.for_points))
        return " ".join([found, *lasting])


class SimpleLogic(BaseModel):
    """The Simple form: one to three conditions, all joined by and, or all by or."""

    model_config = ConfigDict(extra="forbid")

    conditions: list[SimpleCondition] = Field(min_length=1, max_length=3)
    combine: Literal["and", "or"] = "and"
    clear_after_seconds: float = Field(default=0.0, ge=0, le=24 * 3600)
    # State-based alarming: judged only while this permissive holds (the pump runs), and once
    # it held ``enable_delay_seconds`` (the flow settles after a start). Off: suppressed by
    # design, not raised and not counted.
    enable_when: SimpleCondition | None = None
    enable_delay_seconds: float = Field(default=0.0, ge=0, le=24 * 3600)
    # Limits by product grade: where the grade comes from (each condition lists its limits).
    grade: SimpleGrade | None = None

    @model_validator(mode="after")
    def _permissive(self) -> SimpleLogic:
        if self.enable_when is not None and self.enable_when.input != "value":
            raise ValueError(t("a permissive is a value (a pump's run signal), not an event"))
        if self.enable_when is None:
            self.enable_delay_seconds = 0.0
        if self.enable_when is not None:
            self.enable_when.grade_limits = []
        graded = any(item.grade_limits for item in self.conditions)
        if graded and self.grade is None:
            raise ValueError(t("limits by grade need where the grade comes from"))
        if self.grade is not None and not graded:
            raise ValueError(t("give at least one grade its limit, or remove the grade"))
        return self

    def sentence(self) -> str:
        joiner = f" {t('and') if self.combine == 'and' else t('or')} "
        words = joiner.join(item.words() for item in self.conditions)
        if self.enable_when is not None:
            words += t("; only while {permissive}", permissive=self.enable_when.words())
            if self.enable_delay_seconds:
                words += t(
                    " (from {time} after it starts holding)",
                    time=seconds_words(self.enable_delay_seconds),
                )
        if self.grade is not None:
            words += t("; the grade from {grade}", grade=self.grade.words())
        if self.clear_after_seconds:
            words += t(
                "; clears after {time} back to normal", time=seconds_words(self.clear_after_seconds)
            )
        return words


def span(minutes: int) -> str:
    if minutes % (24 * 60) == 0:
        return f"{minutes // (24 * 60)} d"
    if minutes % 60 == 0:
        return f"{minutes // 60} h"
    return f"{minutes} min"


def seconds_words(seconds: float) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        return span(int(seconds // 60))
    return f"{seconds:g} s"


def _label(text: str, used: set[str]) -> str:
    """A Python-friendly label for a value (inputs.<label> in a Python block)."""

    base = "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")[:30] or "value"
    if base[0].isdigit():
        base = f"v_{base}"
    label, number = base, 2
    while label in used:
        label, number = f"{base}_{number}", number + 1
    used.add(label)
    return label


def to_diagram(logic: SimpleLogic) -> dict[str, Any]:
    """The rule's diagram from the Simple form, laid out left to right."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    used: set[str] = set()

    def node(block: str, column: int, row: int, parameters: dict | None = None, **extra) -> str:
        node_id = f"n{len(nodes) + 1}"
        nodes.append(
            {
                "id": node_id,
                "block": block,
                "parameters": parameters or {},
                "x": 40 + 240 * column,
                "y": 40 + 140 * row,
                **extra,
            }
        )
        return node_id

    def wire(source: str, port: str, target: str, target_port: str) -> None:
        edges.append(
            {"source": source, "source_port": port, "target": target, "target_port": target_port}
        )

    graded_rows = [0]

    def grade_limit(item: SimpleCondition, row: int) -> str:
        """The Grade limit block of a condition (below every condition), fed by the grade."""

        grade = logic.grade
        assert grade is not None
        graded_rows[0] += 1
        below = len(logic.conditions) + (1 if logic.enable_when is not None else 0)
        where = below + graded_rows[0] - 1
        limits = [entry.model_dump() for entry in item.grade_limits]
        if grade.source == "value" and grade.value is not None:
            block = node(GRADE_BLOCK, 1, where, {"limits": limits})
            source = node(
                VALUE_BLOCK,
                0,
                where,
                {"signal": grade.value.signal, "role": grade.value.role, "unit": ""},
                label=_label(grade.value.name or grade.value.role or "grade", used),
            )
            wire(source, "value", block, "grade")
            return block
        return node(GRADE_BLOCK, 1, where, {"limits": limits, "kinds": grade.kinds,
                                            "about": grade.about, "field": grade.field})  # fmt: skip

    def chain(item: SimpleCondition, row: int) -> str:
        """The blocks of one condition; answers "node:port" of its last output."""

        if item.input == "value":
            assert item.value is not None
            source = node(
                VALUE_BLOCK,
                0,
                row,
                {"signal": item.value.signal, "role": item.value.role, "unit": item.value.unit},
                label=_label(item.value.name or item.value.role or item.value.signal, used),
            )
            if item.op in ("between", "outside"):
                test = node(
                    "alarm.between",
                    1,
                    row,
                    {"low": item.limit, "high": item.high, "inside": item.op == "between"},
                )
            elif item.op == "changed":
                test = node("alarm.changed", 1, row)
            elif item.op == "unchanged":
                # A frozen value: "changed" negated; with "for at least" it is a stuck transmitter.
                moved = node("alarm.changed", 1, row)
                wire(source, "value", moved, "value")
                test = node("alarm.not", 2, row)
                wire(moved, "condition", test, "condition")
                source = ""
            else:
                test = node(
                    "alarm.compare",
                    1,
                    row,
                    {"op": item.op, "limit": item.limit, "deadband": item.deadband},
                )
                if item.grade_limits and logic.grade is not None:
                    wire(grade_limit(item, row), "limit", test, "limit")
            if source:
                wire(source, "value", test, "value")
            end, port = test, "condition"
        else:
            assert item.event is not None
            given = {
                "kinds": item.event.kinds,
                "severities": item.event.severities,
                "about": item.event.about,
            }
            label = _label(item.event.name or item.event.kinds[0].rpartition(".")[2], used)
            if item.test == "count":
                source = node(
                    "alarm.event_count",
                    0,
                    row,
                    {**given, "window_minutes": item.window_minutes},
                    label=label,
                )
                end = node("alarm.compare", 1, row, {"op": ">=", "limit": float(item.count)})
                wire(source, "count", end, "value")
                port = "condition"
            else:
                end = node("alarm.event_open", 0, row, given, label=label)
                port = "open"
        if item.for_seconds or item.for_points:
            held = node(
                "alarm.for", 2, row, {"seconds": item.for_seconds, "points": item.for_points}
            )
            wire(end, port, held, "condition")
            end, port = held, "condition"
        return f"{end}:{port}"

    ends = [chain(item, row) for row, item in enumerate(logic.conditions)]
    if len(ends) > 1:
        joined = node(f"alarm.{logic.combine}", 3, 0)
        for item in ends:
            source, _, port = item.partition(":")
            wire(source, port, joined, "conditions")
        last, last_port = joined, "condition"
    else:
        last, _, last_port = ends[0].partition(":")
    raising: dict[str, Any] = {"clear_after_seconds": logic.clear_after_seconds}
    if logic.enable_when is not None:
        raising["enable_delay_seconds"] = logic.enable_delay_seconds
    alarm = node(ALARM_BLOCK, 4, 0, raising)
    wire(last, last_port, alarm, "condition")
    if logic.enable_when is not None:
        source, _, port = chain(logic.enable_when, len(logic.conditions)).partition(":")
        wire(source, port, alarm, "enabled")
    return {"version": 2, "nodes": nodes, "edges": edges}
