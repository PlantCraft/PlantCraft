"""Statistics: numbers that summarise a series over the window, and the time it spent outside
its limits.

Every block reads the samples with a value, and only those inside the optional *Only where*
condition (steady operation, a grade, the unit running), so a statistic describes the part of the
window it is meant to.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, NoData, Result, inport, outport
from pydantic import BaseModel, Field, model_validator

from linkcraft.blocks.base import condition, numeric, seconds, within
from linkcraft.i18n import t

LIBRARY = "stats"
X = inport("x", "series", "Signal", "The series summarised over the window.")
WHEN = inport(
    "when",
    "intervals",
    "Only where",
    "The part of the window counted (steady operation, say). Not wired: all of it.",
    required=False,
)
NIST = (
    "NIST/SEMATECH e-Handbook of Statistical Methods (2012), National Institute of Standards and "
    "Technology, section 1.3.5: measures of location and scale."
)
MONTGOMERY = "Montgomery, D. C. (2019). Introduction to Statistical Quality Control, 8th ed. Wiley."
HYNDMAN_FAN = (
    "Hyndman, R. J., Fan, Y. (1996). Sample quantiles in statistical packages. The American "
    "Statistician 50(4), 361-365 (definition 7, linear interpolation)."
)
FREEDMAN_DIACONIS = (
    "Freedman, D., Diaconis, P. (1981). On the histogram as a density estimator: L2 theory. "
    "Zeitschrift für Wahrscheinlichkeitstheorie und verwandte Gebiete 57, 453-476."
)
PAGE = "Page, E. S. (1954). Continuous inspection schemes. Biometrika 41(1/2), 100-115."
BASSEVILLE = (
    "Basseville, M., Nikiforov, I. V. (1993). Detection of Abrupt Changes: Theory and "
    "Application. Prentice Hall."
)
BAUER = (
    "Bauer, M., Horch, A., Xie, L., Jelali, M., Thornhill, N. (2016). The current state of "
    "control loop performance monitoring: a survey of application in industry. Journal of "
    "Process Control 38, 1-10."
)
MIN_SAMPLES = 2


def _values(inputs: dict[str, Any]) -> pd.Series | NoData:
    found = within(inputs["x"], inputs.get("when"))
    if len(found) < MIN_SAMPLES:
        return NoData(t("Fewer than {n} samples with a value.", n=MIN_SAMPLES))
    return found


def _one(compute: Any) -> Any:
    def run(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
        found = _values(inputs)
        if isinstance(found, NoData):
            return {"value": found}
        return {"value": float(compute(found, parameters))}

    return run


class Percentile(BaseModel):
    percent: float = Field(
        default=95.0,
        ge=0,
        le=100,
        title="Percentile",
        description="The share of the samples at or below the value given: 50 is the median.",
        json_schema_extra={"unit": "%"},
    )


class Histogram(BaseModel):
    bins: int = Field(
        default=0,
        ge=0,
        le=200,
        title="Bins",
        description="How many equal bins span the values; 0 chooses them from the data "
        "(Freedman-Diaconis).",
    )


def _bins(values: np.ndarray, wanted: int) -> int:
    if wanted:
        return wanted
    q1, q3 = np.percentile(values, [25, 75])
    width = 2.0 * (q3 - q1) / len(values) ** (1.0 / 3.0)
    span = float(values.max() - values.min())
    if width <= 0 or span <= 0:
        return 1
    return int(min(100, max(1, np.ceil(span / width))))


def _histogram(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    found = _values(inputs)
    if isinstance(found, NoData):
        return {"result": found, "mode": found}
    values = found.to_numpy(dtype=float)
    counts, edges = np.histogram(values, bins=_bins(values, parameters.bins))
    top = int(np.argmax(counts))
    mode = float((edges[top] + edges[top + 1]) / 2.0)
    q1, median, q3 = (float(item) for item in np.percentile(values, [25, 50, 75]))
    message = t(
        "Half of the {n} samples lie between {q1} and {q3} (median {median}); the most frequent "
        "values are around {mode}.",
        n=len(values),
        q1=f"{q1:.4g}",
        q3=f"{q3:.4g}",
        median=f"{median:.4g}",
        mode=f"{mode:.4g}",
    )
    detail = {
        "edges": [float(item) for item in edges],
        "counts": [int(item) for item in counts],
        "quartiles": [q1, median, q3],
        "samples": len(values),
    }
    return {"result": Result("ok", None, message, t("Distribution"), detail), "mode": mode}


class Correlation(BaseModel):
    max_lag_seconds: float = Field(
        default=0.0,
        ge=0,
        le=86_400,
        title="Largest lag",
        description="How far B may trail or lead A; the lag with the strongest correlation "
        "wins. 0: no lag.",
        json_schema_extra={"unit": "s"},
    )


def _correlation(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    a = numeric(inputs["a"])
    b = numeric(inputs["b"]).reindex(a.index)
    keep = condition(inputs.get("when"), a.index)
    step = float(ctx.sample_seconds or 0.0) or float(np.median(np.diff(seconds(a.index))) or 1.0)
    lags = int(parameters.max_lag_seconds // step) if step > 0 else 0
    best: tuple[float, int] | None = None
    for lag in range(-lags, lags + 1):
        shifted = b.shift(lag)
        pair = pd.concat([a, shifted], axis=1)[keep].dropna()
        if len(pair) < 3 or pair.iloc[:, 0].std() == 0 or pair.iloc[:, 1].std() == 0:
            continue
        r = float(np.corrcoef(pair.iloc[:, 0], pair.iloc[:, 1])[0, 1])
        if best is None or abs(r) > abs(best[0]) + 1e-12:
            best = (r, lag)
    if best is None:
        reason = NoData(t("Not enough samples where both series vary."))
        return {"r": reason, "lag": reason}
    return {"r": best[0], "lag": best[1] * step}


class Steps(BaseModel):
    window_samples: int = Field(
        default=10,
        ge=2,
        le=10_000,
        title="Samples each side",
        description="How many samples before and after a moment are averaged to compare them.",
    )
    sigmas: float = Field(
        default=5.0,
        gt=0,
        le=100,
        title="Threshold (noise sigmas)",
        description="How many times the noise of the averages a change must exceed to count "
        "as a step.",
    )
    min_size: float = Field(
        default=0.0,
        ge=0,
        title="Smallest step",
        description="Steps smaller than this, in the signal's unit, are ignored; 0: any size.",
    )


def _steps(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    x = numeric(inputs["x"])
    n = parameters.window_samples
    if x.notna().sum() < 2 * n + 1:
        reason = NoData(t("Fewer than {n} samples with a value.", n=2 * n + 1))
        return {"count": reason, "largest": reason, "intervals": reason}
    before = x.rolling(n, min_periods=n).mean()
    after = x[::-1].rolling(n, min_periods=n).mean()[::-1].shift(-1)
    change = after - before
    # The noise of one sample, robustly from successive differences (a step moves few of them).
    differences = x.diff().dropna()
    sigma = float(np.median(np.abs(differences - differences.median()))) * 1.4826 / np.sqrt(2.0)
    threshold = max(parameters.sigmas * sigma * np.sqrt(2.0 / n), parameters.min_size)
    candidate = change.abs() > threshold if threshold > 0 else change.abs() > 0
    candidate = candidate.fillna(False).to_numpy(dtype=bool)
    marks = np.zeros(len(x), dtype=bool)
    sizes: list[float] = []
    start = None
    values = change.to_numpy(dtype=float)
    for index, flag in enumerate([*candidate, False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            part = np.abs(values[start:index])
            peak = start + int(np.nanargmax(part))
            marks[peak] = True
            sizes.append(float(values[peak]))
            start = None
    largest = max(sizes, key=abs) if sizes else 0.0
    intervals = pd.Series(marks, index=x.index, name="steps")
    return {"count": float(len(sizes)), "largest": largest, "intervals": intervals}


class OutsideLimits(BaseModel):
    lower: float | None = Field(
        default=None,
        title="Lower limit",
        description="Below it the signal is outside; empty: no lower limit.",
    )
    upper: float | None = Field(
        default=None,
        title="Upper limit",
        description="Above it the signal is outside; empty: no upper limit.",
    )

    @model_validator(mode="after")
    def _limits(self) -> OutsideLimits:
        if self.lower is None and self.upper is None:
            raise ValueError("give a lower limit, an upper limit or both")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("the lower limit is above the upper limit")
        return self


def _outside(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    x = numeric(inputs["x"])
    counted = condition(inputs.get("when"), x.index) & x.notna()
    if counted.sum() < MIN_SAMPLES:
        reason = NoData(t("Fewer than {n} samples with a value.", n=MIN_SAMPLES))
        return {"share": reason, "minutes": reason, "intervals": reason}
    outside = pd.Series(False, index=x.index)
    if parameters.lower is not None:
        outside |= x < parameters.lower
    if parameters.upper is not None:
        outside |= x > parameters.upper
    outside &= counted
    # Each sample stands for the time to the next one (the last: the median step).
    times = seconds(x.index)
    spans = np.diff(times, append=times[-1] + (np.median(np.diff(times)) if len(times) > 1 else 0))
    total = float(spans[counted.to_numpy()].sum())
    out = float(spans[outside.to_numpy()].sum())
    outside.name = "outside limits"
    return {
        "share": 100.0 * out / total if total > 0 else 0.0,
        "minutes": out / 60.0,
        "intervals": outside,
    }


def _number_block(
    block_id: str, name: str, docs: BlockDocs, compute: Any, parameters: Any = None
) -> Block:
    spec = BlockSpec(
        block_id,
        "1.0",
        LIBRARY,
        name,
        docs,
        inputs=(X, WHEN),
        outputs=(outport("value", "number", name, docs.reading.split(";")[0].rstrip(".") + "."),),
        group="Location and spread",
        **({"parameters": parameters} if parameters else {}),
    )
    return Block(spec, _one(compute))


BLOCKS = (
    _number_block(
        "stats.mean",
        "Mean",
        BlockDocs(
            summary="The mean of a series over the window (or only where a condition holds).",
            description=(
                "Averages the samples with a value, all of the window or only the part a "
                "condition marks, such as steady operation. The mean is where the signal sat; "
                "compare it with a target or a limit with Limits to verdict."
            ),
            reading="The average value, in the signal's unit; outliers pull it.",
            formula="x̄ = (1/n) Σ x(t)",
            references=(NIST, MONTGOMERY),
        ),
        lambda values, _p: values.mean(),
    ),
    _number_block(
        "stats.std",
        "Standard deviation",
        BlockDocs(
            summary="The standard deviation of a series over the window: how much it varies.",
            description=(
                "The spread of the samples around their mean (the sample standard deviation). "
                "A tighter spread means a steadier variable; compare it before and after a "
                "change, or turn it into a verdict with Limits."
            ),
            reading="The typical distance from the mean, in the signal's unit; 0 is constant.",
            formula="s = sqrt( Σ (x(t) − x̄)² / (n − 1) )",
            references=(NIST, MONTGOMERY),
        ),
        lambda values, _p: values.std(ddof=1),
    ),
    _number_block(
        "stats.percentile",
        "Percentile",
        BlockDocs(
            summary="The value a given share of the samples stays at or below (50: the median).",
            description=(
                "Sorts the samples and gives the value below which the chosen percent of them "
                "lie, interpolating between neighbours. The median (50) is the typical value "
                "untouched by outliers; 5 and 95 bound the usual range."
            ),
            reading="A value in the signal's unit; the chosen share of samples is at or below it.",
            formula="Q(p) by linear interpolation between order statistics (Hyndman-Fan type 7)",
            references=(HYNDMAN_FAN, NIST),
        ),
        lambda values, p: np.percentile(values.to_numpy(dtype=float), p.percent),
        Percentile,
    ),
    Block(
        BlockSpec(
            "stats.histogram",
            "1.0",
            LIBRARY,
            "Histogram",
            BlockDocs(
                summary="How the values of a series are distributed over the window.",
                description=(
                    "Counts the samples in equal bins between the smallest and the largest "
                    "value. The verdict's sentence says where half of the values lie and which "
                    "values are the most frequent, and its detail keeps the bins and counts; a "
                    "second peak shows two operating points, a long tail rare excursions."
                ),
                reading="Not a judgement: the verdict is always normal and carries the bins; "
                "the number is the most frequent value.",
                formula="counts_k = #{ x(t) in [e_k, e_k+1) }, bin width 2·IQR / n^(1/3) by "
                "default",
                references=(FREEDMAN_DIACONIS, NIST),
            ),
            inputs=(X, WHEN),
            outputs=(
                outport(
                    "result",
                    "result",
                    "Distribution",
                    "The bins and counts in its detail, and a sentence on where values lie.",
                ),
                outport(
                    "mode",
                    "number",
                    "Most frequent value",
                    "The centre of the bin with the most samples.",
                ),
            ),
            parameters=Histogram,
            group="Distribution",
        ),
        _histogram,
    ),
    Block(
        BlockSpec(
            "stats.correlation",
            "1.0",
            LIBRARY,
            "Correlation",
            BlockDocs(
                summary="How closely two series move together, with the lag that fits best.",
                description=(
                    "Pearson's correlation of A and B over the samples where both have a value: "
                    "near 1 they rise and fall together, near −1 one rises as the other falls, "
                    "near 0 they are unrelated. With a largest lag, B is shifted back and forth "
                    "and the strongest correlation is kept, so a delay between them does not hide "
                    "it."
                ),
                reading="r from −1 to 1, and the lag in seconds (positive: B trails A).",
                formula="r = Σ (a − ā)(b − b̄) / sqrt( Σ (a − ā)² Σ (b − b̄)² ), maximised over "
                "the lag",
                limitations=(
                    "Correlation is not cause: a third variable may move both.",
                    "A shared trend correlates two unrelated signals: detrend them first.",
                ),
                references=(NIST,),
            ),
            inputs=(
                inport("a", "series", "A", "The first series."),
                inport("b", "series", "B", "The second series, shifted to find the lag."),
                WHEN,
            ),
            outputs=(
                outport("r", "number", "Correlation", "Pearson's r, from −1 to 1.", low=-1, high=1),
                outport(
                    "lag", "number", "Lag", "Lag of B behind A with the strongest r.", unit="s"
                ),
            ),
            parameters=Correlation,
            group="Relations",
        ),
        _correlation,
    ),
    Block(
        BlockSpec(
            "stats.steps",
            "1.0",
            LIBRARY,
            "Step changes",
            BlockDocs(
                summary="Finds the moments a series jumped to a new level, and how far.",
                description=(
                    "Compares the mean of the samples just before each moment with the mean "
                    "just after it; where the difference exceeds the threshold, a multiple of "
                    "the signal's noise, the moment is a step (a setpoint change, a valve moved, "
                    "a bias in a sensor). Each run of such moments counts once, at its largest "
                    "change."
                ),
                reading="How many steps, the largest one (signed, in the signal's unit) and when "
                "they happened.",
                formula="d(t) = mean(x(t+1..t+n)) − mean(x(t−n+1..t)); step where |d| > k·σ·sqrt(2/n)",
                assumptions=(
                    "The noise σ is estimated from successive differences (median absolute "
                    "deviation), so a few steps do not inflate it.",
                ),
                limitations=("A slow ramp is not a step: use Derivative for ramps.",),
                references=(BASSEVILLE, PAGE),
            ),
            inputs=(X,),
            outputs=(
                outport("count", "number", "Steps", "How many steps were found.", better="lower"),
                outport("largest", "number", "Largest step", "The largest step, signed."),
                outport("intervals", "intervals", "Step moments", "True at each step."),
            ),
            parameters=Steps,
            group="Changes",
        ),
        _steps,
    ),
    Block(
        BlockSpec(
            "stats.outside_limits",
            "1.0",
            LIBRARY,
            "Time outside limits",
            BlockDocs(
                summary="How long a series spent below its lower or above its upper limit.",
                description=(
                    "Adds up the time the signal was outside its operating window (a quality "
                    "specification, an operating envelope) and its share of the time counted, "
                    "all of the window or only where a condition holds. It is the time-in-limits "
                    "key figure of performance monitoring; Limits turns the share into a verdict."
                ),
                reading="The share in % and the minutes outside; 0 means always inside.",
                formula="share = Σ Δt (x outside) / Σ Δt (counted) · 100",
                references=(BAUER, MONTGOMERY),
            ),
            inputs=(X, WHEN),
            outputs=(
                outport(
                    "share",
                    "number",
                    "Share outside",
                    "Share of the counted time outside the limits.",
                    unit="%",
                    low=0,
                    high=100,
                    better="lower",
                ),
                outport(
                    "minutes",
                    "number",
                    "Time outside",
                    "Minutes outside the limits.",
                    unit="min",
                    better="lower",
                ),
                outport("intervals", "intervals", "Outside", "True where the signal was outside."),
            ),
            parameters=OutsideLimits,
            group="Operating window",
        ),
        _outside,
    ),
)

__all__ = ["BLOCKS"]
