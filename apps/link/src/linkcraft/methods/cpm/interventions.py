"""Operational interventions inferred from setpoint and mode changes."""

from __future__ import annotations

import numpy as np
import pandas as pd
from plantcraft_sdk.methods import (
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    OutputPort,
)
from plantcraft_sdk.methods.findings import counted as _counted
from plantcraft_sdk.methods.findings import fmt_number as _n
from plantcraft_sdk.methods.utils import (
    clamp_score,
    duration_hours,
    insufficient_data,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import (
    BAUER_2016_CPM_SURVEY,
    JELALI_2006_CPA_OVERVIEW,
)


class InterventionInput(BaseModel):
    dataset: LoopDataset


class InterventionParameters(BaseModel):
    sp_change_threshold: float = Field(
        default=0.1, ge=0.0, description="Minimum SP movement counted as an intervention."
    )
    reference_hours: float = Field(default=12.0, gt=0.0)
    full_performance_max: float = Field(default=2.0, ge=0.0)
    zero_performance_min: float = Field(default=12.0, gt=0.0)


METHOD_METADATA = MethodMetadata(
    method_id="operational_interventions",
    name="Operational interventions",
    description="Setpoint changes and mode switches made by operators in the window.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY, JELALI_2006_CPA_OVERVIEW],
    required_signals=["sp", "mode"],
    implemented_formula="SP changes + mode switches, normalized to a reference window; performance interpolated between accepted and excessive intervention counts.",
    assumptions=["SP and mode changes represent relevant interventions in the analysed window."],
    limitations=["Recipes, APC, start-ups and transitions can produce expected interventions."],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version="1.0.0",
    input_ports=[
        InputPort(port_id="sp", semantic_type="setpoint", dtype="timeseries_float", required=False),
        InputPort(
            port_id="mode",
            semantic_type="controller_mode",
            dtype="timeseries_string",
            required=False,
        ),
    ],
    input_schema=InterventionInput,
    parameter_schema=InterventionParameters,
    output_ports=[
        OutputPort(port_id="sp_changes", semantic_type="count", dtype="integer"),
        OutputPort(port_id="mode_switches", semantic_type="count", dtype="integer"),
        OutputPort(port_id="interventions_reference_window", semantic_type="count", dtype="float"),
        OutputPort(
            port_id="performance_component", semantic_type="score", dtype="float", unit="percent"
        ),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: InterventionInput, parameters: InterventionParameters) -> MethodResult:
    dataset = input_data.dataset
    if "sp" not in dataset.data and "mode" not in dataset.data:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("SP or mode is required to count interventions."),
            ["sp", "mode"],
        )
    sp_changes = 0
    valid_samples = 0
    if "sp" in dataset.data:
        sp = pd.to_numeric(dataset.data["sp"], errors="coerce").dropna()
        valid_samples = max(valid_samples, len(sp))
        if len(sp) > 1:
            sp_changes = int(
                np.sum(np.abs(np.diff(sp.to_numpy(dtype=float))) > parameters.sp_change_threshold)
            )
    mode_switches = 0
    if "mode" in dataset.data:
        mode = dataset.data["mode"].dropna().astype(str).str.strip().str.lower()
        valid_samples = max(valid_samples, len(mode))
        if len(mode) > 1:
            mode_switches = int(np.sum(mode.to_numpy()[1:] != mode.to_numpy()[:-1]))
    if valid_samples < 2:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("At least two valid samples are required.")
        )
    hours = duration_hours(dataset)
    total = sp_changes + mode_switches
    normalized = float(total * parameters.reference_hours / hours) if hours > 0 else float(total)
    span = max(parameters.zero_performance_min - parameters.full_performance_max, 1e-9)
    performance = clamp_score(100.0 * (parameters.zero_performance_min - normalized) / span)
    if normalized <= parameters.full_performance_max:
        performance = 100.0
    score = 100.0 - performance
    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Operational interventions calculated from SP and mode changes."),
        metrics={
            "sp_changes": sp_changes,
            "mode_switches": mode_switches,
            "total_interventions": total,
            "interventions_per_hour": float(total / hours) if hours > 0 else 0.0,
            "interventions_reference_window": normalized,
            "reference_hours": parameters.reference_hours,
            "performance_component": performance,
        },
    )


def describe(metrics: dict) -> str:
    sp = _counted(metrics.get("sp_changes"), "{count} setpoint change", "{count} setpoint changes")
    mode = _counted(metrics.get("mode_switches"), "{count} mode switch", "{count} mode switches")
    window = _counted(
        metrics.get("interventions_reference_window"),
        "{count} intervention",
        "{count} interventions",
    )
    hours = _n(metrics.get("reference_hours", 12))
    return t(
        "{sp} and {mode} in the window, equivalent to {window} every {hours} h.",
        sp=sp,
        mode=mode,
        window=window,
        hours=hours,
    )
