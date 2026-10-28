"""Controller output saturation monitoring."""

from __future__ import annotations

from plantcraft_sdk.methods import (
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    OutputPort,
)
from plantcraft_sdk.methods.findings import fmt_percent as _pct
from plantcraft_sdk.methods.utils import (
    insufficient_data,
    missing_columns,
    numeric_series,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import BAUER_2016_CPM_SURVEY


class SaturationInput(BaseModel):
    dataset: LoopDataset


class SaturationParameters(BaseModel):
    lower_limit: float = 0.0
    upper_limit: float = 100.0
    margin: float = Field(default=1.0, ge=0.0)
    warning_fraction: float = Field(default=0.05, ge=0.0, le=1.0)


METHOD_METADATA = MethodMetadata(
    method_id="op_saturation_fraction",
    name="Controller output saturation fraction",
    description="Share of the time the controller output sits at its low or high limit.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY],
    required_signals=["op"],
    implemented_formula="saturated=(op<=lower+margin) or (op>=upper-margin); score=saturated_fraction/warning_fraction.",
    assumptions=["The OP limits and engineering unit are configured correctly."],
    limitations=[
        "Saturation may be caused by process constraints rather than a malfunctioning controller."
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(
            port_id="op",
            semantic_type="controller_output",
            dtype="timeseries_float",
            required=True,
            unit="percent",
        )
    ],
    input_schema=SaturationInput,
    parameter_schema=SaturationParameters,
    output_ports=[
        OutputPort(port_id="saturation_fraction", semantic_type="fraction", dtype="float")
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: SaturationInput, parameters: SaturationParameters) -> MethodResult:
    dataset = input_data.dataset
    missing = missing_columns(dataset, ["op"])
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("OP is required for saturation monitoring."),
            missing,
        )

    op = numeric_series(dataset, "op")
    if op.empty:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("OP does not contain numeric data.")
        )

    saturated = (op <= parameters.lower_limit + parameters.margin) | (
        op >= parameters.upper_limit - parameters.margin
    )
    fraction = float(saturated.mean())
    score = (
        min(100.0, 100.0 * fraction / parameters.warning_fraction)
        if parameters.warning_fraction > 0
        else 0.0
    )

    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Controller output saturation fraction calculated."),
        metrics={
            "saturation_fraction": fraction,
            "performance_component": 100.0 * (1.0 - fraction),
            "saturated_samples": int(saturated.sum()),
            "valid_samples": int(len(op)),
            "lower_limit": parameters.lower_limit,
            "upper_limit": parameters.upper_limit,
            "margin": parameters.margin,
        },
    )


def describe(metrics: dict) -> str:
    return t(
        "The controller output was at its limits {fraction} of the time.",
        fraction=_pct(metrics.get("saturation_fraction")),
    )
