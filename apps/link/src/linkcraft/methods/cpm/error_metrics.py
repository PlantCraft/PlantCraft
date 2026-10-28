"""Error integral metrics for PV-SP tracking, scored against a tolerance on the loop's own scale.

The method's reference (Bauer et al. 2016) is about ranking a plant's whole loop population by
KPIs. An error in the PV's engineering unit cannot be ranked that way: a mean error of 1 is
nothing for a flow of 500 t/h and a lot for a pressure of 2 bar. So, unless an algorithm or loop
gives an absolute ``error_tolerance``, the tolerance is a share of the loop's scale: the PV span
when it is known (``pv_span``), else the size of the setpoint (median |SP|). The default 4 %
means a mean error of 1 % of the scale costs 25 points. Only when neither scale exists (an SP
at zero) the absolute fallback applies, and the result says which basis it used.
"""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import (
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    OutputPort,
)
from plantcraft_sdk.methods.findings import fmt_number as _n
from plantcraft_sdk.methods.findings import fmt_percent as _pct
from plantcraft_sdk.methods.utils import (
    estimate_sample_seconds,
    insufficient_data,
    missing_columns,
    normalized_score,
    numeric_frame,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import BAUER_2016_CPM_SURVEY


class ErrorMetricsInput(BaseModel):
    dataset: LoopDataset


# Used only when the loop has no scale (no span given and an SP at zero).
ABSOLUTE_TOLERANCE = 1.0
ABSOLUTE_BAND = 0.5


class ErrorMetricsParameters(BaseModel):
    error_tolerance: float | None = Field(
        default=None,
        gt=0.0,
        description="Absolute MAE (PV unit) that scores 100; empty: a share of the loop's scale.",
    )
    acceptable_band: float | None = Field(
        default=None,
        gt=0.0,
        description="Absolute PV-SP band considered on target; empty: a share of the scale.",
    )
    relative_tolerance_percent: float = Field(
        default=4.0, gt=0.0, description="MAE that scores 100, in percent of the loop's scale."
    )
    relative_band_percent: float = Field(
        default=1.0, gt=0.0, description="On-target band, in percent of the loop's scale."
    )
    pv_span: float | None = Field(
        default=None, gt=0.0, description="PV span (engineering range); empty: median |SP|."
    )


METHOD_METADATA = MethodMetadata(
    method_id="error_metrics_basic",
    name="Basic PV-SP error metrics",
    description="How closely the PV follows the setpoint: mean absolute error and time within a band.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY],
    required_signals=["pv", "sp"],
    implemented_formula=(
        "error=pv-sp; IAE=sum(abs(error))*dt; ISE=sum(error^2)*dt; score=MAE/tolerance, "
        "tolerance=error_tolerance or relative_tolerance_percent/100*scale, "
        "scale=pv_span or median(|SP|)."
    ),
    assumptions=[
        "PV and SP are expressed in the same engineering unit.",
        "SP movement is meaningful for the selected window.",
        "Without a span, the setpoint's size is the loop's scale (a PV far from zero).",
    ],
    limitations=[
        "High error may be caused by external constraints or disturbances, not only by poor tuning.",
        "A setpoint near zero (a gauge pressure, a differential) makes the relative tolerance "
        "tight: give the loop its pv_span or an absolute error_tolerance.",
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(
            port_id="pv", semantic_type="process_variable", dtype="timeseries_float", required=True
        ),
        InputPort(port_id="sp", semantic_type="setpoint", dtype="timeseries_float", required=True),
    ],
    input_schema=ErrorMetricsInput,
    parameter_schema=ErrorMetricsParameters,
    output_ports=[
        OutputPort(port_id="mae", semantic_type="metric", dtype="float"),
        OutputPort(port_id="rmse", semantic_type="metric", dtype="float"),
        OutputPort(port_id="iae", semantic_type="integral_metric", dtype="float"),
        OutputPort(port_id="ise", semantic_type="integral_metric", dtype="float"),
        OutputPort(port_id="itae", semantic_type="integral_metric", dtype="float"),
        OutputPort(port_id="within_band_fraction", semantic_type="fraction", dtype="float"),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: ErrorMetricsInput, parameters: ErrorMetricsParameters) -> MethodResult:
    dataset = input_data.dataset
    missing = missing_columns(dataset, ["pv", "sp"])
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("PV and SP are required for error metrics."),
            missing,
        )

    frame = numeric_frame(dataset, ["pv", "sp"])
    if frame.empty:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("PV and SP do not contain aligned numeric data.")
        )

    error = frame["pv"].to_numpy(dtype=float) - frame["sp"].to_numpy(dtype=float)
    dt = estimate_sample_seconds(dataset, frame.index)
    abs_error = np.abs(error)
    mae = float(np.mean(abs_error))
    rmse = float(np.sqrt(np.mean(error**2)))
    iae = float(np.sum(abs_error) * dt)
    ise = float(np.sum(error**2) * dt)
    elapsed = np.arange(len(error), dtype=float) * dt
    itae = float(np.sum(elapsed * abs_error) * dt)
    tolerance, band, scale, basis = _tolerances(parameters, frame["sp"].to_numpy(dtype=float))
    within_band_fraction = float(np.mean(abs_error <= band))
    score = normalized_score(mae, tolerance)

    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("PV-SP tracking error calculated."),
        metrics={
            "mean_error": float(np.mean(error)),
            "mae": mae,
            "rmse": rmse,
            "max_abs_error": float(np.max(abs_error)),
            "iae": iae,
            "ise": ise,
            "itae": itae,
            "iae_per_hour": float(iae / max(len(error) * dt / 3600.0, 1e-9)),
            "within_band_fraction": within_band_fraction,
            "acceptable_band": band,
            "error_tolerance": tolerance,
            "scale": scale,
            "tolerance_basis": basis,
            "mae_percent_of_scale": (100.0 * mae / scale) if scale else None,
            "performance_component": 100.0 - score,
            "sample_seconds": dt,
            "valid_samples": int(len(frame)),
        },
    )


def _tolerances(
    parameters: ErrorMetricsParameters, sp: np.ndarray
) -> tuple[float, float, float | None, str]:
    """(tolerance, band, scale, basis): absolute when given, else shares of the loop's scale."""

    if parameters.pv_span:
        scale, basis = float(parameters.pv_span), "pv_span"
    else:
        finite = np.abs(sp[np.isfinite(sp)])
        scale = float(np.median(finite)) if finite.size else 0.0
        basis = "setpoint"
    if not np.isfinite(scale) or scale <= 1e-9:
        scale, basis = None, "absolute"
    tolerance = parameters.error_tolerance or (
        parameters.relative_tolerance_percent / 100.0 * scale if scale else ABSOLUTE_TOLERANCE
    )
    band = parameters.acceptable_band or (
        parameters.relative_band_percent / 100.0 * scale if scale else ABSOLUTE_BAND
    )
    if parameters.error_tolerance:
        basis = "absolute"
    return float(tolerance), float(band), scale, basis


def describe(metrics: dict) -> str:
    band = metrics.get("acceptable_band")
    inside = metrics.get("within_band_fraction")
    mae = _n(metrics.get("mae"))
    if inside is not None and band is not None:
        return t(
            "PV–SP mean absolute error of {mae}; the PV was within ±{band} of the setpoint {inside} of the time.",
            mae=mae,
            band=_n(band),
            inside=_pct(inside),
        )
    return t("PV–SP mean absolute error of {mae}.", mae=mae)
