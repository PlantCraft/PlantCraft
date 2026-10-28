"""Manual-mode fraction monitoring."""

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
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import BAUER_2016_CPM_SURVEY


class ManualModeInput(BaseModel):
    dataset: LoopDataset


class ManualModeParameters(BaseModel):
    manual_labels: list[str] = Field(default_factory=lambda: ["manual", "man", "m"])
    warning_fraction: float = Field(default=0.10, ge=0.0, le=1.0)


METHOD_METADATA = MethodMetadata(
    method_id="manual_mode_fraction",
    name="Manual mode fraction",
    description="Share of the time the loop runs in manual instead of automatic.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY],
    required_signals=["mode"],
    implemented_formula="manual_fraction=count(mode in manual_labels)/count(valid_mode); score=manual_fraction/warning_fraction.",
    assumptions=["The mode tag is reliable and its labels are configured correctly."],
    limitations=[
        "Manual operation may be intentional during maintenance, start-up or abnormal conditions."
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(
            port_id="mode",
            semantic_type="controller_mode",
            dtype="timeseries_string",
            required=True,
        )
    ],
    input_schema=ManualModeInput,
    parameter_schema=ManualModeParameters,
    output_ports=[OutputPort(port_id="manual_fraction", semantic_type="fraction", dtype="float")],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: ManualModeInput, parameters: ManualModeParameters) -> MethodResult:
    dataset = input_data.dataset
    missing = missing_columns(dataset, ["mode"])
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("Mode signal is required for manual-mode fraction."),
            missing,
        )

    mode = dataset.data["mode"].dropna().astype(str).str.strip().str.lower()
    if mode.empty:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("Mode signal does not contain valid values.")
        )

    manual_labels = {label.strip().lower() for label in parameters.manual_labels}
    manual_count = int(mode.isin(manual_labels).sum())
    fraction = float(manual_count / len(mode))
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
        message=t("Manual-mode fraction calculated."),
        metrics={
            "manual_fraction": fraction,
            "automatic_fraction": 1.0 - fraction,
            "performance_component": 100.0 * (1.0 - fraction),
            "manual_samples": manual_count,
            "valid_samples": int(len(mode)),
        },
    )


def describe(metrics: dict) -> str:
    return t(
        "The loop was out of automatic {fraction} of the time.",
        fraction=_pct(metrics.get("manual_fraction")),
    )
