"""Reconciliation: balances closed within the meters' uncertainty, and the meter that is wrong.

"Mass balance reconciliation" takes up to eight flows and the balances they must satisfy
(``s1 + s2 = s3; s3 = s4 + s5``), gives every flow's reconciled value at each step and judges the
window: do the balances close within the meters' uncertainty, and if not, which meter has a
gross error and how big it is. "Redundant pair drift" watches two meters of the same quantity
drift apart. The math is ``linkcraft.methods.reconciliation``; the pair's filter is the SDK's local level
Kalman filter, as in "Kalman filter".
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, NoData, Result, inport, outport
from plantcraft_sdk.estimators import local_level, noise_variance, tune
from pydantic import BaseModel, Field, field_validator

from linkcraft.blocks.base import clean, numeric
from linkcraft.blocks.estimators import HARVEY, KALMAN, LIBRARY, MIN_SAMPLES
from linkcraft.i18n import t
from linkcraft.methods.reconciliation import (
    BalanceError,
    parse_balances,
    reconcile,
    reconcile_series,
)

STREAMS = tuple(f"s{k}" for k in range(1, 9))
NARASIMHAN = (
    "Narasimhan, S., Jordache, C. (2000). Data Reconciliation and Gross Error Detection. "
    "Gulf Publishing."
)
MAH = (
    "Mah, R. S. H., Tamhane, A. C. (1982). Detection of gross errors in process data. "
    "AIChE Journal 28(5), 828-830."
)
CROWE = (
    "Crowe, C. M., Garcia Campos, Y. A., Hrymak, A. (1983). Reconciliation of process flow rates "
    "by matrix projection. AIChE Journal 29(6), 881-888."
)


def _percents(text: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for part in re.split(r"[;\n,]", text):
        if not part.strip():
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        try:
            number = float(value)
        except ValueError:
            raise ValueError(t("Not 'stream = percent': {part}", part=part.strip()[:40])) from None
        if name not in STREAMS or not 0 < number <= 100:
            raise ValueError(t("Not 'stream = percent': {part}", part=part.strip()[:40]))
        found[name] = number
    return found


class ReconciliationParameters(BaseModel):
    balances: str = Field(
        default="s1 = s2",
        min_length=1,
        max_length=2000,
        title="Balances",
        description="One balance per node, separated by ';': what goes in = what goes out, with "
        "the streams' ports, e.g. 's1 + s2 = s3; s3 = s4 + s5'. A factor multiplies a stream: "
        "'0.5*s5'. 's1 = s2' is two meters of the same flow.",
    )
    uncertainty_percent: float = Field(
        default=2.0,
        gt=0,
        le=50,
        title="Meter uncertainty",
        description="One standard deviation of each meter, in % of its mean reading on the window.",
        json_schema_extra={"unit": "%"},
    )
    uncertainties: str = Field(
        default="",
        max_length=500,
        title="Uncertainty by meter",
        description="Optional, for the meters that differ: 's3 = 1; s5 = 4' (in %).",
    )
    test_level_percent: float = Field(
        default=5.0,
        gt=0,
        le=20,
        title="Test level",
        description="How often the test may call a gross error when there is none.",
        json_schema_extra={"unit": "%"},
    )

    @field_validator("uncertainties")
    @classmethod
    def _uncertainties(cls, value: str) -> str:
        _percents(value)
        return value


def _streams(inputs: dict[str, Any]) -> tuple[list[str], pd.DataFrame]:
    wired = [name for name in STREAMS if isinstance(inputs.get(name), pd.Series)]
    frame = pd.concat({name: numeric(inputs[name]) for name in wired}, axis=1).sort_index()
    return wired, frame.ffill(limit=3)


def _reconcile(
    inputs: dict[str, Any], parameters: ReconciliationParameters, _ctx: Any
) -> dict[str, Any]:
    wired, frame = _streams(inputs)

    def nothing(reason: str) -> dict[str, Any]:
        missing = NoData(reason)
        out: dict[str, Any] = {f"r{name[1:]}": missing for name in STREAMS}
        out.update(imbalance=missing, result=Result("unknown", None, reason, t("Balance")))
        return out

    try:
        a = parse_balances(parameters.balances, wired)
    except BalanceError as error:
        return nothing(t("The balances cannot be read: {error}", error=str(error)))
    complete = frame.dropna()
    if len(complete) < 10:
        return nothing(t("Fewer than {n} samples with every stream.", n=10))
    y = frame.to_numpy(dtype=float)
    means = complete.mean().to_numpy(dtype=float)
    scale = np.where(np.abs(means) > 1e-9 * max(1.0, float(np.abs(means).max())), np.abs(means), 0)
    scale[scale == 0] = float(np.abs(means).max()) or 1.0
    percents = _percents(parameters.uncertainties)
    pct = np.array([percents.get(name, parameters.uncertainty_percent) for name in wired])
    variances = (pct / 100.0 * scale) ** 2
    reconciled = reconcile_series(a, y, variances)
    window = reconcile(a, means, variances, alpha=parameters.test_level_percent / 100.0)

    out: dict[str, Any] = {f"r{name[1:]}": NoData(t("Not wired.")) for name in STREAMS}
    for k, name in enumerate(wired):
        out[f"r{name[1:]}"] = clean(pd.Series(reconciled[:, k], index=frame.index))
    out["imbalance"] = clean(pd.Series(y @ a[0], index=frame.index))
    out["result"] = _verdict(wired, means, window)
    return out


def _verdict(wired: list[str], means: np.ndarray, window: Any) -> Result:
    detail = {
        "gamma": window.gamma,
        "critical": window.critical,
        "z": {name: float(window.z[k]) for k, name in enumerate(wired)},
        "z_critical": window.z_critical,
        "means": {name: float(means[k]) for k, name in enumerate(wired)},
        "reconciled": {name: float(window.values[k]) for k, name in enumerate(wired)},
        "redundant": [name for k, name in enumerate(wired) if window.redundant[k]],
        "suspects": [],
    }
    score = float(max(0.0, min(100.0, 100.0 * (1.0 - window.gamma / (2.0 * window.critical)))))
    if np.isinf(window.critical):
        return Result(
            "unknown",
            None,
            t(
                "No redundancy: the balances can only be solved, not "
                "checked. Add a meter or a balance."
            ),
            t("Balance"),
            detail,
        )
    if not window.gross_error:
        message = t(
            "The balances close within the meters' uncertainty (test {gamma} of {critical}).",
            gamma=f"{window.gamma:.3g}",
            critical=f"{window.critical:.3g}",
        )
        return Result("ok", score, message, t("Balance"), detail)
    found = []
    for k in window.suspects:
        # Meters the test cannot tell apart (same z, same balances) share the suspicion.
        alike = [
            wired[j]
            for j in range(len(wired))
            if j != k
            and window.redundant[j]
            and abs(window.z[j] - window.z[k]) <= 1e-6 * max(1.0, window.z[k])
        ]
        bias = float(window.adjustments[k])
        share = bias / means[k] * 100.0 if means[k] else float("nan")
        detail["suspects"].append(
            {
                "stream": wired[k],
                "bias": bias,
                "percent": share,
                "z": float(window.z[k]),
                "alike": alike,
            }
        )
        text = t(
            "{name} reads {bias} ({share}%) off",
            name=wired[k],
            bias=f"{bias:+.4g}",
            share=f"{share:+.3g}",
        )
        found.append(text + (t(" (or {names})", names=", ".join(alike)) if alike else ""))
    message = t(
        "A gross error: the balances miss by more than the meters' uncertainty (test {gamma} of "
        "{critical}). {found}.",
        gamma=f"{window.gamma:.3g}",
        critical=f"{window.critical:.3g}",
        found="; ".join(found),
    )
    return Result("bad", min(score, 40.0), message, t("Balance"), detail)


class PairParameters(BaseModel):
    tolerance_percent: float = Field(
        default=1.0,
        gt=0,
        le=50,
        title="Tolerance",
        description="A drift smaller than this, in % of the meters' mean reading, is accepted.",
        json_schema_extra={"unit": "%"},
    )
    sigmas: float = Field(
        default=3.0,
        ge=1,
        le=10,
        title="Confidence",
        description="How many standard deviations of its estimate the drift must exceed.",
    )


def _pair(inputs: dict[str, Any], parameters: PairParameters, _ctx: Any) -> dict[str, Any]:
    a = numeric(inputs["a"])
    b = numeric(inputs["b"]).reindex(a.index).ffill(limit=3)
    difference = (a - b).dropna()
    if len(difference) < MIN_SAMPLES:
        reason = NoData(t("Fewer than {n} samples with both meters.", n=MIN_SAMPLES))
        return {
            "drift": reason,
            "uncertainty": reason,
            "result": Result("unknown", None, str(reason.reason), t("Pair")),
        }
    d = difference.to_numpy(dtype=float)
    _, filtered = tune(lambda q: local_level(q, noise_variance(d)), d)
    drift = pd.Series(filtered.estimate, index=difference.index)
    spread = pd.Series(np.sqrt(filtered.variances[0]), index=difference.index)
    level = float(np.nanmean(np.abs(np.concatenate([a.to_numpy(float), b.to_numpy(float)]))))
    last, sigma = float(drift.iloc[-1]), float(spread.iloc[-1])
    tolerance = parameters.tolerance_percent / 100.0 * level
    share = last / level * 100.0 if level else float("nan")
    detail = {"drift": last, "uncertainty": sigma, "percent": share, "tolerance": tolerance}
    off = abs(last) > parameters.sigmas * sigma and abs(last) > tolerance
    score = float(max(0.0, 100.0 * (1.0 - abs(last) / (2.0 * tolerance)))) if tolerance else None
    if off:
        message = t(
            "The meters drifted apart: a reads {drift} ({share}%) more than b, beyond the "
            "tolerance. Two meters cannot tell which one drifted; a third meter or a balance can.",
            drift=f"{last:+.4g}",
            share=f"{share:+.3g}",
        )
        return {
            "drift": clean(drift),
            "uncertainty": clean(spread),
            "result": Result("bad", min(score or 0.0, 40.0), message, t("Pair"), detail),
        }
    message = t(
        "The meters agree: a reads {drift} ({share}%) apart from b.",
        drift=f"{last:+.4g}",
        share=f"{share:+.3g}",
    )
    return {
        "drift": clean(drift),
        "uncertainty": clean(spread),
        "result": Result("ok", score, message, t("Pair"), detail),
    }


def _stream_port(name: str, required: bool) -> Any:
    return inport(
        name,
        "series",
        f"Stream {name[1:]}",
        f"A flow in the balances, by its port name ({name}).",
        required=required,
    )


BLOCKS = (
    Block(
        BlockSpec(
            "estimator.reconcile",
            "1.0",
            LIBRARY,
            "Mass balance reconciliation",
            BlockDocs(
                summary="Flows that close their balances, and the meter with a gross error when "
                "they do not.",
                description=(
                    "Adjusts the measured flows as little as their uncertainty allows so that "
                    "every balance closes (weighted least squares), at each step. On the "
                    "window's mean it tests whether the balances miss by more than the meters' "
                    "uncertainty (global test) and, when they do, which meter is wrong "
                    "(measurement test), dropping the most suspect one and testing again until "
                    "the rest agree (serial elimination). A meter on its own, in no balance "
                    "with other meters, is never judged."
                ),
                reading="ok: the balances close within the uncertainty. bad: a gross error, "
                "with the meter and its bias (what it reads minus what the balances say). "
                "unknown: no redundancy (as many unknowns as balances) or too little data. On "
                "a five-stream, two-node test a 10% bias on one meter is named on a 2% meter "
                "uncertainty.",
                assumptions=(
                    "The process is near steady state over the window (no hold-up change).",
                    "The meters' errors are independent; the uncertainty is one standard "
                    "deviation, in % of the reading.",
                ),
                limitations=(
                    "Linear balances only (total mass or volume), no energy or components yet.",
                    "Meters in exactly the same balances (two in series) cannot be told apart: "
                    "both are named.",
                    "Every stream needs a meter; unmeasured streams are for a later version.",
                ),
                formula="x̂ = y − ΣAᵀ(AΣAᵀ)⁻¹Ay; γ = rᵀ(AΣAᵀ)⁻¹r ~ χ²(m); z_i = |a_i|/√W_ii",
                references=(NARASIMHAN, MAH, CROWE),
            ),
            inputs=tuple(_stream_port(name, name in ("s1", "s2")) for name in STREAMS),
            outputs=(
                *(
                    outport(
                        f"r{name[1:]}",
                        "series",
                        f"Reconciled {name[1:]}",
                        f"Stream {name[1:]} after reconciliation.",
                    )
                    for name in STREAMS
                ),
                outport(
                    "imbalance",
                    "series",
                    "Imbalance",
                    "What the first balance misses by, on the raw readings.",
                ),
                outport(
                    "result",
                    "result",
                    "Balance",
                    "Whether the balances close, and the meter with a gross error.",
                ),
            ),
            parameters=ReconciliationParameters,
            group="Reconciliation",
        ),
        _reconcile,
    ),
    Block(
        BlockSpec(
            "estimator.pair_drift",
            "1.0",
            LIBRARY,
            "Redundant pair drift",
            BlockDocs(
                summary="Whether two meters of the same quantity drift apart, and by how much.",
                description=(
                    "Filters the difference between the two meters with a Kalman filter (a "
                    "local level tuned by maximum likelihood): the noise averages out and a "
                    "slow drift stands out, with its uncertainty."
                ),
                reading="ok: the drift is within the tolerance or not clear of its "
                "uncertainty. bad: the meters drifted apart by more than the tolerance and "
                "the chosen number of standard deviations.",
                assumptions=("Both meters measure the same quantity, in the same unit.",),
                limitations=(
                    "Two meters cannot tell which one drifted: a third meter or a balance "
                    "(Mass balance reconciliation) can.",
                    "Needs at least 60 samples with both meters.",
                ),
                formula="d(k) = a(k) − b(k) = δ(k) + v(k); δ(k+1) = δ(k) + w(k)",
                references=(KALMAN, HARVEY, NARASIMHAN),
            ),
            inputs=(
                inport("a", "series", "Meter a", "One meter of the quantity."),
                inport("b", "series", "Meter b", "The other meter of the same quantity."),
            ),
            outputs=(
                outport("drift", "series", "Drift", "How much a reads above b, filtered."),
                outport("uncertainty", "series", "Uncertainty", "One standard deviation of it."),
                outport("result", "result", "Pair", "Whether the meters drifted apart."),
            ),
            parameters=PairParameters,
            group="Reconciliation",
        ),
        _pair,
    ),
)
