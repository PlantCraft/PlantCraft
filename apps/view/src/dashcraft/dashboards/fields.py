"""How a card shows its values (round 7, after Grafana's field config): units, min and max,
decimals, colours, thresholds, value mappings and line styles, set once for the card
(``field``) and changed for some of its signals (``overrides``).

Thresholds are a list of steps: a value takes the last step whose value it reaches (the first
step, without a value, is the base below all the others). Each step has a colour and a level
(``ok``, ``warning``, ``alarm``, or ``none`` for a colour that is not a state), so a table or a
KPI says "Alarm" in words and colour, and the Desk can count it. The suite's colour of the
level is used unless the step names its own.
"""

from __future__ import annotations

import fnmatch
import math
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from dashcraft.i18n import t

# A colour: "#rrggbb", or a name of the suite's palette (resolved by the interface).
COLOR = r"^(#[0-9a-fA-F]{6}|[a-z][a-z0-9-]{0,29})?$"
PALETTE = ("blue", "green", "yellow", "orange", "red", "purple", "teal", "grey")
MAX_STEPS = 20
MAX_MAPPINGS = 30
MAX_OVERRIDES = 20
TABLE_COLUMNS = ("last", "mean", "min", "max", "std", "unit", "time", "state")
DEFAULT_TABLE_COLUMNS = ["last", "mean", "min", "max"]

Level = Literal["ok", "warning", "alarm", "none"]


def _finite(value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError(t("A limit must be a finite number."))
    return value


class Step(BaseModel):
    """One threshold: from ``value`` up, the values take this colour and level."""

    value: float | None = None
    color: str = Field(default="", max_length=30, pattern=COLOR)
    level: Level = "ok"

    _value = field_validator("value")(lambda cls, value: _finite(value))


class Thresholds(BaseModel):
    """Absolute values, or percentages between the field's min and max."""

    mode: Literal["absolute", "percentage"] = "absolute"
    steps: list[Step] = Field(default_factory=list, max_length=MAX_STEPS)
    # How charts draw them: not at all, dashed lines, coloured bands, or both.
    show: Literal["off", "lines", "area", "lines+area"] = "lines"

    @model_validator(mode="after")
    def _ordered(self) -> Thresholds:
        if not self.steps:
            return self
        base = [step for step in self.steps if step.value is None]
        if len(base) > 1:
            raise ValueError(t("Thresholds have one base step (without a value)."))
        rest = sorted((step for step in self.steps if step.value is not None), key=_at)
        values = [step.value for step in rest]
        if len(values) != len(set(values)):
            raise ValueError(t("Two thresholds have the same value."))
        self.steps = (base or [Step(level="ok")]) + rest
        return self

    def step(self, value: float | None, low: float | None, high: float | None) -> Step | None:
        """The step a value is in, or None (no value, no thresholds, or a percentage without
        a range)."""

        if value is None or not self.steps:
            return None
        at = value
        if self.mode == "percentage":
            if low is None or high is None or not high > low:
                return None
            at = (value - low) / (high - low) * 100
        found = self.steps[0]
        for step in self.steps[1:]:
            if step.value is not None and at >= step.value:
                found = step
        return found


def _at(step: Step) -> float:
    return step.value if step.value is not None else -math.inf


class Mapping(BaseModel):
    """A value shown as words and a colour: an exact value, a range, or a text."""

    type: Literal["value", "range", "text"] = "value"
    value: str = Field(default="", max_length=60)
    low: float | None = None
    high: float | None = None
    text: str = Field(default="", max_length=40)
    color: str = Field(default="", max_length=30, pattern=COLOR)
    # A mapped value can also be a state (a valve "Fault" is an alarm).
    level: Literal["", "ok", "warning", "alarm"] = ""

    _ends = field_validator("low", "high")(lambda cls, value: _finite(value))

    def matches(self, value: Any) -> bool:
        if self.type == "text":
            return isinstance(value, str) and value.strip().lower() == self.value.strip().lower()
        number = finite_number(value)
        if number is None:
            return False
        if self.type == "range":
            low = -math.inf if self.low is None else self.low
            high = math.inf if self.high is None else self.high
            return low <= number <= high
        try:
            return float(self.value) == number
        except ValueError:
            return False


class FieldConfig(BaseModel):
    """Every option is optional: none means "as the card's defaults, else automatic"."""

    unit: str | None = Field(default=None, max_length=20)
    min: float | None = None
    max: float | None = None
    decimals: int | None = Field(default=None, ge=0, le=6)
    display_name: str | None = Field(default=None, max_length=80)
    no_value: str | None = Field(default=None, max_length=20)
    # How values are coloured: by their threshold, one colour, or the palette (one per line).
    color_mode: Literal["thresholds", "fixed", "palette"] | None = None
    color: str | None = Field(default=None, max_length=30, pattern=COLOR)
    thresholds: Thresholds | None = None
    mappings: list[Mapping] | None = Field(default=None, max_length=MAX_MAPPINGS)
    # Lines of time charts (as in Trends).
    draw: Literal["lines", "points", "lines+points", "bars"] | None = None
    interpolation: Literal["linear", "smooth", "step"] | None = None
    line_width: float | None = Field(default=None, ge=0.5, le=8)
    dash: Literal["solid", "dash", "dot", "dashdot"] | None = None
    fill: int | None = Field(default=None, ge=0, le=100)
    axis: Literal["auto", "left", "right", "hidden"] | None = None
    # The normal (desired) operating range (ISA-101): a darker band on the analog indicator and
    # under a stat's line. None: between the thresholds' normal step and the next one.
    normal_low: float | None = None
    normal_high: float | None = None

    _ends = field_validator("min", "max", "normal_low", "normal_high")(
        lambda cls, value: _finite(value)
    )

    @model_validator(mode="after")
    def _range(self) -> FieldConfig:
        if self.min is not None and self.max is not None and self.min >= self.max:
            raise ValueError(t("The minimum must be below the maximum."))
        if (
            self.normal_low is not None
            and self.normal_high is not None
            and self.normal_low >= self.normal_high
        ):
            raise ValueError(t("The normal range's low end must be below its high end."))
        return self

    def merged(self, other: FieldConfig) -> FieldConfig:
        """This config with every option ``other`` sets."""

        return FieldConfig.model_validate(
            {**self.model_dump(exclude_none=True), **other.model_dump(exclude_none=True)}
        )


class Matcher(BaseModel):
    """Which signals of a card an override changes: by role (every PV), by signal id, or by the
    name shown (``*`` matches anything: ``FIC-1*``)."""

    by: Literal["role", "signal", "name"] = "role"
    value: str = Field(min_length=1, max_length=120)

    def matches(self, row: dict[str, Any]) -> bool:
        wanted = self.value.strip().lower()
        if self.by == "role":
            return (row.get("role") or "").lower() == wanted
        found = row.get("signal") if self.by == "signal" else row.get("label")
        return fnmatch.fnmatchcase(str(found or "").lower(), wanted)


class Override(BaseModel):
    match: Matcher
    field: FieldConfig = Field(default_factory=FieldConfig)


def effective(defaults: FieldConfig, overrides: list[Override], row: dict[str, Any]) -> FieldConfig:
    """The options of one signal: the card's, then each matching override in order."""

    found = defaults
    for override in overrides:
        if override.match.matches(row):
            found = found.merged(override.field)
    return found


def state_of(config: FieldConfig, value: Any, row: dict[str, Any]) -> str:
    """``alarm``, ``warning``, ``ok`` (the suite's status words), or ``none``: no value, no
    threshold, or a step that is only a colour. A mapping with a level wins."""

    for mapping in config.mappings or []:
        if mapping.matches(value) and mapping.level:
            return mapping.level
    number = finite_number(value)
    thresholds = config.thresholds
    if number is None or thresholds is None or not thresholds.steps:
        return "none"
    low = config.min if config.min is not None else finite_number(row.get("low"))
    high = config.max if config.max is not None else finite_number(row.get("high"))
    step = thresholds.step(number, low, high)
    if step is None or step.level == "none":
        return "none"
    return step.level


def finite_number(value: Any) -> float | None:
    """A finite number as a float; anything else (a bool, text, NaN, infinity) is None."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def legacy_thresholds(old: dict[str, Any] | None) -> Thresholds | None:
    """The four limits of cards before round 7 (low alarm, low warning, high warning, high
    alarm) as steps: alarm below the low alarm, warning below the low warning, ok, then
    warning and alarm from the high limits."""

    if not isinstance(old, dict):
        return None
    values = {
        key: finite_number(old.get(key))
        for key in ("low_alarm", "low_warn", "high_warn", "high_alarm")
    }
    if all(value is None for value in values.values()):
        return None
    base: Level = (
        "alarm"
        if values["low_alarm"] is not None
        else "warning"
        if values["low_warn"] is not None
        else "ok"
    )
    steps = [Step(level=base)]
    taken: set[float] = set()
    for key, level in (
        ("low_alarm", "warning" if values["low_warn"] is not None else "ok"),
        ("low_warn", "ok"),
        ("high_warn", "warning"),
        ("high_alarm", "alarm"),
    ):
        value = values[key]
        if value is not None and value not in taken:
            taken.add(value)
            steps.append(Step(value=value, level=level))  # type: ignore[arg-type]
    return Thresholds(steps=steps)
