"""Transforms: a new series from one or more series (arithmetic, filters, engineering units and
the operating window)."""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any, Literal

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, NoParameters, inport, outport
from pydantic import BaseModel, Field, field_validator, model_validator

from linkcraft.blocks.base import clean, condition, numeric, seconds


class MovingAverage(BaseModel):
    window_samples: int = Field(
        default=5,
        ge=1,
        le=10_000,
        title="Window (samples)",
        description="How many grid samples each average spans; a longer window smooths more.",
    )


class FirstOrderFilter(BaseModel):
    time_constant_seconds: float = Field(
        default=60.0,
        gt=0,
        title="Time constant",
        description="Time the filter takes to follow 63% of a step, in seconds.",
        json_schema_extra={"unit": "s"},
    )


class GainOffset(BaseModel):
    gain: float = Field(
        default=1.0, title="Gain", description="Multiplies every value (a unit conversion factor)."
    )
    offset: float = Field(
        default=0.0, title="Offset", description="Added to every value after the gain."
    )


class Clip(BaseModel):
    lower: float = Field(
        default=0.0, title="Lower limit", description="Values below it are set to it."
    )
    upper: float = Field(
        default=100.0, title="Upper limit", description="Values above it are set to it."
    )


class Delay(BaseModel):
    samples: int = Field(
        default=1,
        ge=0,
        le=10_000,
        title="Delay (samples)",
        description="How many grid samples the signal is shifted later in time.",
    )


class Derivative(BaseModel):
    per: Literal["s", "min", "h"] = Field(
        default="min",
        title="Rate per",
        description="The time unit of the rate: per second, per minute or per hour.",
    )


class Resample(BaseModel):
    period_seconds: float = Field(
        default=600.0,
        ge=1,
        le=7 * 86_400,
        title="Period",
        description="Length of each period the samples are gathered into, in seconds.",
        json_schema_extra={"unit": "s"},
    )
    how: Literal["mean", "min", "max", "last"] = Field(
        default="mean",
        title="Value of a period",
        description="What each period's samples become: their mean, minimum, maximum or last.",
    )


# What an expression may use besides its four inputs, numbers and + − × ÷ and powers.
FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": np.abs,
    "sqrt": np.sqrt,
    "exp": np.exp,
    "log": np.log,
    "log10": np.log10,
    "sin": np.sin,
    "cos": np.cos,
    "min": np.minimum,
    "max": np.maximum,
}
NAMES = ("a", "b", "c", "d")
OPERATORS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: lambda x, y: x + y,
    ast.Sub: lambda x, y: x - y,
    ast.Mult: lambda x, y: x * y,
    ast.Div: lambda x, y: x / y,
    ast.Pow: lambda x, y: x**y,
}


def _parsed(text: str) -> ast.expr:
    """The expression's tree, checked: only a to d, numbers, + − × ÷ **, and FUNCTIONS."""

    tree = ast.parse(text.strip(), mode="eval").body

    def check(node: ast.AST) -> None:
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            check(node.left)
            check(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            check(node.operand)
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
            pass
        elif isinstance(node, ast.Name) and node.id in NAMES:
            pass
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FUNCTIONS
            and not node.keywords
            and 1 <= len(node.args) <= 2
        ):
            for argument in node.args:
                check(argument)
        else:
            raise ValueError(
                "use a, b, c, d, numbers, + - * / ** and " + ", ".join(sorted(FUNCTIONS))
            )

    check(tree)
    return tree


class Expression(BaseModel):
    expression: str = Field(
        default="a * b / c",
        min_length=1,
        max_length=200,
        title="Expression",
        description=(
            "A formula of the inputs a, b, c and d, numbers, + - * / ** and abs, sqrt, exp, log, "
            "log10, sin, cos, min, max; for example a * b / c."
        ),
    )

    @field_validator("expression")
    @classmethod
    def _expression(cls, value: str) -> str:
        try:
            _parsed(value)
        except SyntaxError as exc:
            raise ValueError(f"not a formula: {exc.msg}") from exc
        return value.strip()


def _expression(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> pd.Series:
    tree = _parsed(parameters.expression)
    values = {name: numeric(inputs[name]) for name in NAMES if inputs.get(name) is not None}

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.BinOp):
            return OPERATORS[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp):
            value = evaluate(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise ValueError(f"the expression uses {node.id}, which is not wired")
            return values[node.id]
        call = node  # checked by _parsed: a call of FUNCTIONS
        return FUNCTIONS[call.func.id](*(evaluate(item) for item in call.args))  # type: ignore[attr-defined]

    with np.errstate(all="ignore"):
        found = evaluate(tree)
    if not isinstance(found, pd.Series):
        first = next(iter(values.values()), None)
        if first is None:
            raise ValueError("wire at least one input")
        found = pd.Series(float(found), index=first.index)
    return found.replace([np.inf, -np.inf], np.nan)


# Engineering units by quantity: a unit's value in the quantity's base unit is
# value * scale + offset (temperature is the only quantity with an offset).
UNITS: dict[str, dict[str, tuple[float, float]]] = {
    "temperature": {"°C": (1.0, 273.15), "K": (1.0, 0.0), "°F": (5.0 / 9.0, 255.372222222)},
    "pressure": {
        "kPa": (1.0, 0.0),
        "Pa": (0.001, 0.0),
        "bar": (100.0, 0.0),
        "MPa": (1000.0, 0.0),
        "kgf/cm²": (98.0665, 0.0),
        "psi": (6.894757293, 0.0),
        "atm": (101.325, 0.0),
        "mmHg": (0.133322387, 0.0),
    },
    "volume flow": {
        "m³/h": (1.0, 0.0),
        "m³/s": (3600.0, 0.0),
        "m³/d": (1.0 / 24.0, 0.0),
        "L/s": (3.6, 0.0),
        "L/min": (0.06, 0.0),
        "US gal/min": (0.227124707, 0.0),
        "bbl/d": (0.006624471, 0.0),
    },
    "mass flow": {
        "kg/s": (1.0, 0.0),
        "kg/h": (1.0 / 3600.0, 0.0),
        "t/h": (1000.0 / 3600.0, 0.0),
        "t/d": (1000.0 / 86_400.0, 0.0),
        "lb/h": (0.45359237 / 3600.0, 0.0),
    },
    "length": {"m": (1.0, 0.0), "mm": (0.001, 0.0), "cm": (0.01, 0.0), "ft": (0.3048, 0.0)},
    "power": {"kW": (1.0, 0.0), "W": (0.001, 0.0), "MW": (1000.0, 0.0), "hp": (0.745699872, 0.0)},
}
QUANTITY = {unit: quantity for quantity, units in UNITS.items() for unit in units}
Unit = Literal[
    "°C", "K", "°F",
    "kPa", "Pa", "bar", "MPa", "kgf/cm²", "psi", "atm", "mmHg",
    "m³/h", "m³/s", "m³/d", "L/s", "L/min", "US gal/min", "bbl/d",
    "kg/s", "kg/h", "t/h", "t/d", "lb/h",
    "m", "mm", "cm", "ft",
    "kW", "W", "MW", "hp",
]  # fmt: skip


class EngineeringUnit(BaseModel):
    from_unit: Unit = Field(
        default="bar", title="From", description="The unit the incoming series is in."
    )
    to_unit: Unit = Field(
        default="kPa", title="To", description="The unit the series goes on in; same quantity."
    )

    @model_validator(mode="after")
    def _same_quantity(self) -> EngineeringUnit:
        if QUANTITY[self.from_unit] != QUANTITY[self.to_unit]:
            raise ValueError(
                f"{self.from_unit} is a {QUANTITY[self.from_unit]}, "
                f"{self.to_unit} a {QUANTITY[self.to_unit]}"
            )
        return self


def convert(values: Any, from_unit: str, to_unit: str) -> Any:
    units = UNITS[QUANTITY[from_unit]]
    scale, offset = units[from_unit]
    to_scale, to_offset = units[to_unit]
    return ((values * scale + offset) - to_offset) / to_scale


class OperationFilter(BaseModel):
    after_start_seconds: float = Field(
        default=1800.0,
        ge=0,
        le=7 * 86_400,
        title="Left out after a start",
        description="Time after each start-up the unit is not yet steady and is left out.",
        json_schema_extra={"unit": "s"},
    )
    before_stop_seconds: float = Field(
        default=600.0,
        ge=0,
        le=7 * 86_400,
        title="Left out before a stop",
        description="Time before each shutdown the unit is already leaving and is left out.",
        json_schema_extra={"unit": "s"},
    )


def _steady(running: pd.Series, after_start: float, before_stop: float) -> pd.Series:
    """The running samples far enough from a start or a stop seen in the window. A run that was
    already going when the window began, or still goes at its end, is not cut there."""

    times = seconds(running.index)
    flags = running.to_numpy(dtype=bool)
    steady = np.zeros(len(flags), dtype=bool)
    starts = np.flatnonzero(flags & ~np.r_[False, flags[:-1]])
    ends = np.flatnonzero(flags & ~np.r_[flags[1:], False])
    for first, last in zip(starts, ends, strict=True):
        begin = times[first] + (after_start if first > 0 else 0.0)
        finish = times[last] - (before_stop if last < len(flags) - 1 else 0.0)
        part = slice(first, last + 1)
        steady[part] = (times[part] >= begin) & (times[part] <= finish)
    return pd.Series(steady, index=running.index, name="steady operation")


def _operation_filter(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    x = numeric(inputs["x"])
    steady = _steady(
        condition(inputs["running"], x.index),
        parameters.after_start_seconds,
        parameters.before_stop_seconds,
    )
    return {"value": clean(x.where(steady)), "intervals": steady}


def _derivative(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> pd.Series:
    x = numeric(inputs["x"])
    elapsed = pd.Series(seconds(x.index), index=x.index).diff()
    per = {"s": 1.0, "min": 60.0, "h": 3600.0}[parameters.per]
    return (x.diff() / elapsed * per).replace([np.inf, -np.inf], np.nan)


def _resample(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> pd.Series:
    x = numeric(inputs["x"])
    periods = np.floor(seconds(x.index) / parameters.period_seconds)
    return x.groupby(periods).transform(parameters.how)


def _select(inputs: dict[str, Any], _parameters: Any, _ctx: Any) -> pd.Series:
    a = numeric(inputs["a"])
    b = numeric(inputs["b"]).reindex(a.index) if inputs.get("b") is not None else np.nan
    return a.where(condition(inputs["when"], a.index), b)


def _number(series: Any) -> pd.Series:
    return numeric(series)


def _ewm(inputs: dict[str, Any], parameters: Any, ctx: Any) -> pd.Series:
    step = float(ctx.sample_seconds or 1.0)
    alpha = 1.0 - float(np.exp(-step / parameters.time_constant_seconds))
    return _number(inputs["x"]).ewm(alpha=alpha, adjust=False, ignore_na=True).mean()


def _detrend(inputs: dict[str, Any], _parameters: Any, _ctx: Any) -> pd.Series:
    x = _number(inputs["x"])
    valid = x.dropna()
    if len(valid) < 2:
        return x - x.mean()
    positions = np.arange(len(x), dtype=float)
    mask = x.notna().to_numpy()
    slope, intercept = np.polyfit(positions[mask], valid.to_numpy(dtype=float), 1)
    return x - (slope * positions + intercept)


def _block(
    block_id: str,
    name: str,
    docs: BlockDocs,
    inputs: tuple,
    compute: Callable[[dict[str, Any], Any, Any], pd.Series],
    parameters: type[BaseModel] = NoParameters,
    group: str = "Filters",
) -> Block:
    def run(given: dict[str, Any], values: Any, ctx: Any) -> dict[str, Any]:
        return {"value": clean(compute(given, values, ctx))}

    return Block(
        BlockSpec(
            block_id,
            "1.0",
            "transform",
            name,
            docs,
            inputs=inputs,
            outputs=(
                outport("value", "series", "Result", "The computed series, on the same time grid."),
            ),
            parameters=parameters,
            group=group,
        ),
        run,
    )


X = inport("x", "series", "Signal", "The series to transform, on the algorithm's time grid.")
SEBORG = (
    "Seborg, D. E., Edgar, T. F., Mellichamp, D. A., Doyle, F. J. (2016). Process Dynamics and "
    "Control, 4th ed. Wiley. Chapter 17: digital filtering of process signals."
)
OPPENHEIM = (
    "Oppenheim, A. V., Schafer, R. W. (2010). Discrete-Time Signal Processing, 3rd ed. "
    "Pearson: moving-average (FIR) filters, differentiation and sample-rate change."
)
NIST_SP811 = (
    "Thompson, A., Taylor, B. N. (2008). Guide for the Use of the International System of Units "
    "(SI). NIST Special Publication 811: conversion factors."
)

BLOCKS = (
    _block(
        "transform.error",
        "Control error (SP − PV)",
        BlockDocs(
            summary="The control error: the setpoint minus the process variable at each step.",
            description=(
                "Subtracts the PV from the SP sample by sample. The error is what a controller "
                "acts on, so oscillation and tracking read best on it: it removes the setpoint "
                "moves an operator made from the PV's own movement."
            ),
            reading="Positive when the PV is below its setpoint, negative when above it.",
            formula="e(t) = SP(t) − PV(t)",
        ),
        (
            inport("sp", "series", "SP", "The setpoint, in the PV's unit."),
            inport("pv", "series", "PV", "The process variable."),
        ),
        lambda i, _p, _c: _number(i["sp"]) - _number(i["pv"]),
        group="Arithmetic",
    ),
    _block(
        "transform.subtract",
        "Subtraction (A − B)",
        BlockDocs(
            summary="The difference between two series at each step.",
            description=(
                "Subtracts series B from series A sample by sample, such as two redundant "
                "transmitters or an inlet and an outlet temperature, so the blocks after it "
                "read the difference."
            ),
            reading="Positive when A is above B; in the unit both series share.",
            formula="y(t) = A(t) − B(t)",
        ),
        (
            inport("a", "series", "A", "The series subtracted from."),
            inport("b", "series", "B", "The series subtracted, in the same unit as A."),
        ),
        lambda i, _p, _c: _number(i["a"]) - _number(i["b"]),
        group="Arithmetic",
    ),
    _block(
        "transform.gain_offset",
        "Gain and offset",
        BlockDocs(
            summary="Scales a series and shifts it: a unit conversion or a calibration.",
            description=(
                "Multiplies every value by the gain, then adds the offset. Use it to convert "
                "units (bar to kPa: gain 100) or to apply a known calibration correction "
                "before the blocks that judge the signal."
            ),
            reading="The same signal in the new scale.",
            formula="y(t) = gain · x(t) + offset",
        ),
        (X,),
        lambda i, p, _c: p.gain * _number(i["x"]) + p.offset,
        GainOffset,
        group="Arithmetic",
    ),
    _block(
        "transform.moving_average",
        "Moving average",
        BlockDocs(
            summary="Smooths a series with the mean of a sliding window of samples.",
            description=(
                "Replaces each value with the mean of the last window of grid samples. It "
                "removes fast noise so the blocks after it read the slower movement; a long "
                "window also delays and flattens real changes."
            ),
            reading="The smoothed signal, lagging the original by about half the window.",
            formula="y(t) = mean(x(t − n + 1) … x(t))",
            limitations=("The first samples average fewer values than the window.",),
            references=(OPPENHEIM,),
        ),
        (X,),
        lambda i, p, _c: _number(i["x"]).rolling(p.window_samples, min_periods=1).mean(),
        MovingAverage,
    ),
    _block(
        "transform.first_order_filter",
        "Low-pass filter (first order)",
        BlockDocs(
            summary="Smooths a series like a first-order lag with the chosen time constant.",
            description=(
                "An exponential filter, the low-pass filter of most control systems: each output "
                "moves a fixed share of the way towards the new sample. It removes noise faster "
                "than the time constant and keeps slower movement."
            ),
            reading="The filtered signal, lagging the original by about one time constant.",
            formula="y(t) = y(t−1) + α (x(t) − y(t−1)), α = 1 − exp(−Δt / τ)",
            references=(SEBORG,),
        ),
        (X,),
        _ewm,
        FirstOrderFilter,
    ),
    _block(
        "transform.detrend",
        "Detrend",
        BlockDocs(
            summary="Removes the straight-line trend of the window from a series.",
            description=(
                "Fits a straight line to the window's samples and subtracts it, so a slow drift "
                "or a ramp does not hide the oscillation or the noise the blocks after it look "
                "for."
            ),
            reading="The signal's movement around its trend; its mean is about zero.",
            formula="y(t) = x(t) − (a · t + b), with a and b fitted by least squares",
        ),
        (X,),
        _detrend,
    ),
    _block(
        "transform.difference",
        "Change (Δ)",
        BlockDocs(
            summary="The change of a series from one grid sample to the next.",
            description=(
                "Subtracts each sample's previous value. It turns a level into its rate of "
                "change per step, which shows jumps, valve moves and ramps."
            ),
            reading="Zero while the signal is steady; its size is the step's change.",
            formula="y(t) = x(t) − x(t−1)",
        ),
        (X,),
        lambda i, _p, _c: _number(i["x"]).diff(),
        group="Arithmetic",
    ),
    _block(
        "transform.clip",
        "Clip",
        BlockDocs(
            summary="Holds a series between a lower and an upper limit.",
            description=(
                "Values below the lower limit become the lower limit and values above the upper "
                "limit become the upper limit; values in between pass unchanged. Use it to keep "
                "an output inside 0 to 100% before judging it."
            ),
            reading="The same signal, never outside the two limits.",
            formula="y(t) = min(upper, max(lower, x(t)))",
        ),
        (X,),
        lambda i, p, _c: _number(i["x"]).clip(p.lower, p.upper),
        Clip,
        group="Arithmetic",
    ),
    _block(
        "transform.delay",
        "Delay",
        BlockDocs(
            summary="Shifts a series later in time by a number of grid samples.",
            description=(
                "Moves every value the chosen number of samples later, so a signal can be "
                "compared with another one that reacts after a transport delay or a dead time."
            ),
            reading="The same signal, later; the first samples of the window are empty.",
            formula="y(t) = x(t − n)",
        ),
        (X,),
        lambda i, p, _c: _number(i["x"]).shift(p.samples),
        Delay,
    ),
    _block(
        "transform.derivative",
        "Derivative (rate of change)",
        BlockDocs(
            summary="The rate of change of a series per second, minute or hour.",
            description=(
                "Divides each sample's change by the time since the previous sample, so the "
                "result is a rate whatever the grid's step: a level's rise in % per minute, a "
                "temperature's ramp in °C per hour. A derivative amplifies noise: filter the "
                "signal first (Low-pass filter) when it is noisy."
            ),
            reading="Zero while the signal is steady; positive while it rises, in its unit per "
            "the chosen time.",
            formula="y(t) = (x(t) − x(t−1)) / Δt",
            limitations=("A noisy signal gives a noisy rate: filter it before.",),
            references=(OPPENHEIM, SEBORG),
        ),
        (X,),
        _derivative,
        Derivative,
    ),
    _block(
        "transform.resample",
        "Resample (per period)",
        BlockDocs(
            summary="Gathers the samples into periods and holds each period's mean, min, max or last.",
            description=(
                "Cuts the window into periods of the chosen length from its first sample and "
                "replaces every sample with its period's mean, minimum, maximum or last value. "
                "The series stays on the algorithm's grid, as steps one period long, so it still "
                "wires to any other block: an hourly mean beside the raw signal."
            ),
            reading="A staircase: one value per period, in the signal's unit.",
            formula="y(t) = agg{ x(s) : s in the period of t }",
            limitations=(
                "Each period's value uses all of its samples, the later ones too.",
                "The last period of the window may be shorter than the others.",
            ),
            references=(OPPENHEIM,),
        ),
        (X,),
        _resample,
        Resample,
    ),
    _block(
        "transform.expression",
        "Expression",
        BlockDocs(
            summary="A formula of up to four series, such as a * b / c.",
            description=(
                "Computes a formula sample by sample from the series wired to a, b, c and d: "
                "a mass balance, a ratio, a corrected flow. It accepts numbers, + − × ÷, powers "
                "(**) and abs, sqrt, exp, log, log10, sin, cos, min and max. Nothing else runs: "
                "the formula is checked when the algorithm is saved."
            ),
            reading="The formula's value at each step, in the unit the formula gives.",
            formula="y(t) = f(a(t), b(t), c(t), d(t))",
            limitations=(
                "A division by zero or the log of a negative value leaves that sample empty.",
            ),
        ),
        (
            inport("a", "series", "a", "The series called a in the expression."),
            inport("b", "series", "b", "The series called b in the expression.", required=False),
            inport("c", "series", "c", "The series called c in the expression.", required=False),
            inport("d", "series", "d", "The series called d in the expression.", required=False),
        ),
        _expression,
        Expression,
        group="Arithmetic",
    ),
    _block(
        "transform.unit",
        "Engineering unit",
        BlockDocs(
            summary="Converts a series from one engineering unit to another of the same quantity.",
            description=(
                "Converts temperatures (°C, K, °F), pressures (kPa, Pa, bar, MPa, kgf/cm², psi, "
                "atm, mmHg), volume flows (m³/h, m³/s, m³/d, L/s, L/min, US gal/min, bbl/d), mass "
                "flows (kg/s, kg/h, t/h, t/d, lb/h), lengths (m, mm, cm, ft) and powers (kW, W, "
                "MW, hp) with the SI conversion factors, so blocks that expect a unit get it."
            ),
            reading="The same signal in the new unit.",
            formula="y = ((x · s_from + o_from) − o_to) / s_to, with each unit's factor s and "
            "offset o to the quantity's base unit",
            assumptions=("Gauge or absolute pressure is kept as it is: only the unit changes.",),
            references=(NIST_SP811,),
        ),
        (X,),
        lambda i, p, _c: convert(numeric(i["x"]), p.from_unit, p.to_unit),
        EngineeringUnit,
        group="Arithmetic",
    ),
    _block(
        "transform.select",
        "Select by condition",
        BlockDocs(
            summary="Takes series A where a condition holds, and series B (or nothing) elsewhere.",
            description=(
                "Builds one series from two: A at the samples where the condition is true and B "
                "where it is false, such as the analyser's value when it is valid and the "
                "inferred value otherwise. Without B, the samples outside the condition are "
                "left empty, so the blocks after it judge only the condition's part."
            ),
            reading="A inside the condition, B (or a gap) outside it.",
            formula="y(t) = A(t) if condition(t) else B(t)",
        ),
        (
            inport("when", "intervals", "Condition", "Where A is taken (a Compare block, say)."),
            inport("a", "series", "A", "The series taken where the condition holds."),
            inport(
                "b",
                "series",
                "B",
                "The series taken elsewhere; not wired: a gap.",
                required=False,
            ),
        ),
        _select,
        group="Conditions",
    ),
    Block(
        BlockSpec(
            "transform.operation_filter",
            "1.0",
            "transform",
            "Only in operation",
            BlockDocs(
                summary="Keeps a series only while the unit runs steadily, without start-ups or "
                "shutdowns.",
                description=(
                    "Keeps the samples where the unit runs (the Running intervals, from a Compare "
                    "block on a feed flow or from Unit in operation) and leaves out the chosen "
                    "time after each start-up and before each shutdown seen in the window, when "
                    "the unit is not steady. Statistics and judgements after it then describe "
                    "normal operation only."
                ),
                reading="The signal during steady operation, gaps elsewhere; the intervals say "
                "where.",
                formula="keep x(t) if running(t), t ≥ start + after_start and t ≤ stop − "
                "before_stop",
                assumptions=(
                    "A run already going when the window begins, or still going at its end, is "
                    "not cut there.",
                ),
                references=(
                    "Cao, S., Rhinehart, R. R. (1995). An efficient method for on-line "
                    "identification of steady state. Journal of Process Control 5(6), 363-374.",
                ),
            ),
            inputs=(
                X,
                inport("running", "intervals", "Running", "When the unit runs."),
            ),
            outputs=(
                outport(
                    "value", "series", "Steady", "The signal in steady operation, gaps elsewhere."
                ),
                outport(
                    "intervals",
                    "intervals",
                    "Steady operation",
                    "True where the unit runs steadily.",
                ),
            ),
            parameters=OperationFilter,
            group="Operating window",
        ),
        _operation_filter,
    ),
)
