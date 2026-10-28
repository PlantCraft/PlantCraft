"""Descriptive statistics of the raw process value (informative, never blocks)."""

from __future__ import annotations

import numpy as np
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
from plantcraft_sdk.methods.utils import insufficient_data, result
from pydantic import BaseModel

from linkcraft.i18n import t
from linkcraft.methods.quality._common import numeric, raw_frame


class StatisticsInput(BaseModel):
    dataset: LoopDataset


class StatisticsParameters(BaseModel):
    pass


METHOD_METADATA = MethodMetadata(
    method_id="dq_statistics",
    name="Descriptive statistics",
    description="Mean, spread and range of the PV in the window, for the other methods to read.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    required_signals=["pv"],
    implemented_formula="mean, standard deviation, minimum, maximum and 5th and 95th percentiles of the raw samples.",
    limitations=["Describes the data; does not judge whether it is good or bad."],
)
METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version="1.0.0",
    input_ports=[InputPort(port_id="pv", semantic_type="process_value", dtype="timeseries_float")],
    input_schema=StatisticsInput,
    parameter_schema=StatisticsParameters,
    output_ports=[OutputPort(port_id="mean", semantic_type="process_value", dtype="float")],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)


def run(input_data: StatisticsInput, parameters: StatisticsParameters) -> MethodResult:
    dataset = input_data.dataset
    frame = raw_frame(dataset)
    values = numeric(frame["pv"]) if "pv" in frame.columns else None
    if values is None or len(values) < 2:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("Fewer than two PV samples."), ["pv"]
        )
    array = values.to_numpy(dtype=float)
    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=MethodStatus.OK,
        score=0.0,
        message=t("{count} raw PV samples.", count=len(array)),
        metrics={
            "apt": True,
            "count": int(len(array)),
            "mean": float(np.mean(array)),
            "std": float(np.std(array, ddof=1)),
            "min": float(np.min(array)),
            "max": float(np.max(array)),
            "p05": float(np.percentile(array, 5)),
            "p95": float(np.percentile(array, 95)),
        },
    )
