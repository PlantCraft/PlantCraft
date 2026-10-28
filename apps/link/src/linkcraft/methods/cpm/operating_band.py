"""Time spent inside a configured operating band."""

from __future__ import annotations

from plantcraft_sdk.methods import (
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    MethodStatus,
    OutputPort,
)
from plantcraft_sdk.methods.findings import fmt_number as _n
from plantcraft_sdk.methods.findings import fmt_percent as _pct
from plantcraft_sdk.methods.utils import (
    insufficient_data,
    missing_columns,
    numeric_series,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field, model_validator

from linkcraft.i18n import t
from linkcraft.methods.cpm._surge_level import not_a_surge_level
from linkcraft.methods.references import (
    BAUER_2016_CPM_SURVEY,
    JELALI_2006_CPA_OVERVIEW,
    SHINSKEY_1996_PROCESS_CONTROL_SYSTEMS,
)


class OperatingBandInput(BaseModel):
    dataset: LoopDataset


class OperatingBandParameters(BaseModel):
    lower_limit: float = Field(default=20.0)
    upper_limit: float = Field(default=80.0)
    margin: float = Field(default=0.0, ge=0.0)
    assume_surge_level: bool = Field(
        default=False,
        description="Run on a loop whose asset record gives no loop type (Surge level algorithm).",
    )

    @model_validator(mode="after")
    def validate_limits(self) -> "OperatingBandParameters":
        if self.upper_limit <= self.lower_limit:
            raise ValueError(t("upper_limit must be greater than lower_limit"))
        return self


METHOD_METADATA = MethodMetadata(
    method_id="operating_band_fraction",
    name="Time inside operating band",
    description="Share of the time the PV stays inside its operating band.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[
        BAUER_2016_CPM_SURVEY,
        JELALI_2006_CPA_OVERVIEW,
        SHINSKEY_1996_PROCESS_CONTROL_SYSTEMS,
    ],
    required_signals=["pv"],
    implemented_formula="performance=count(lower<=PV<=upper)/count(valid PV)",
    assumptions=[
        "The configured band represents acceptable operation of the loop. With its own limits "
        "it applies to any loop; with the default 20-80 band only to a surge level (loop type "
        "level, or assume_surge_level)."
    ],
    limitations=[
        "Operating limits can change with production mode or campaign.",
        "With the default band, not applicable to loops that must hold their setpoint (flow, "
        "pressure, temperature, composition) or whose loop type is unknown.",
    ],
)
METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version="1.0.0",
    input_ports=[
        InputPort(port_id="pv", semantic_type="process_variable", dtype="timeseries_float")
    ],
    input_schema=OperatingBandInput,
    parameter_schema=OperatingBandParameters,
    output_ports=[
        OutputPort(port_id="inside_fraction", semantic_type="fraction", dtype="float"),
        OutputPort(
            port_id="performance_component", semantic_type="score", dtype="float", unit="percent"
        ),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)


def run(input_data: OperatingBandInput, parameters: OperatingBandParameters) -> MethodResult:
    dataset = input_data.dataset
    # Limits set for this loop make it a plain time-in-limits KPI that fits any loop; the
    # default 20-80 band, or a surge-level algorithm, keeps the surge-level check.
    generic = (
        bool({"lower_limit", "upper_limit"} & parameters.model_fields_set)
        and not parameters.assume_surge_level
    )
    reason = None if generic else not_a_surge_level(dataset, parameters.assume_surge_level)
    if reason is not None:
        return result(
            metadata=METHOD_METADATA,
            loop_id=dataset.loop_id,
            status=MethodStatus.NOT_APPLICABLE,
            score=0.0,
            message=reason,
        )
    missing = missing_columns(dataset, ["pv"])
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("PV is required for operating-band performance."),
            missing,
        )
    pv = numeric_series(dataset, "pv")
    if pv.empty:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("PV does not contain numeric data.")
        )
    lower = parameters.lower_limit - parameters.margin
    upper = parameters.upper_limit + parameters.margin
    below = pv < lower
    above = pv > upper
    inside = ~(below | above)
    performance = 100.0 * float(inside.mean())
    score = 100.0 - performance
    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Time inside the configured operating band calculated."),
        metrics={
            "inside_fraction": float(inside.mean()),
            "below_fraction": float(below.mean()),
            "above_fraction": float(above.mean()),
            "lower_limit": parameters.lower_limit,
            "upper_limit": parameters.upper_limit,
            "performance_component": performance,
            "valid_samples": len(pv),
        },
    )


def describe(metrics: dict) -> str:
    return t(
        "The PV was inside the {lower} to {upper} band {inside} of the time ({below} below, {above} above).",
        inside=_pct(metrics.get("inside_fraction")),
        lower=_n(metrics.get("lower_limit")),
        upper=_n(metrics.get("upper_limit")),
        below=_pct(metrics.get("below_fraction")),
        above=_pct(metrics.get("above_fraction")),
    )
