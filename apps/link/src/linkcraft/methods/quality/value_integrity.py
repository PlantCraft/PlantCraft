"""Value integrity: invalid values and a frozen process value."""

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
    MethodStatus,
    OutputPort,
)
from plantcraft_sdk.methods.findings import fmt_percent as _pct
from plantcraft_sdk.methods.utils import insufficient_data, result
from pydantic import BaseModel, Field

from linkcraft.i18n import t
from linkcraft.methods.quality._common import raw_frame, window


class ValueIntegrityInput(BaseModel):
    dataset: LoopDataset


class ValueIntegrityParameters(BaseModel):
    frozen_fraction_limit: float = Field(
        default=0.5,
        gt=0.0,
        le=1.0,
        description="Maximum fraction of the window with the PV stuck at the same value.",
    )
    invalid_fraction_limit: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Maximum fraction of invalid samples (text, infinity, empty).",
    )
    lower_limit: float | None = Field(default=None, description="Physical lower limit of the PV.")
    upper_limit: float | None = Field(default=None, description="Physical upper limit of the PV.")


METHOD_METADATA = MethodMetadata(
    method_id="dq_value_integrity",
    name="Value integrity",
    description="Invalid, impossible or frozen PV values in the analysed window.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    required_signals=["pv"],
    implemented_formula=(
        "invalid fraction = non-numeric or out-of-limit samples / total; "
        "frozen fraction = longest stretch with a constant PV / window duration."
    ),
    assumptions=["A real process PV never stays exactly constant for long."],
    limitations=[
        "Calculated or low-resolution signals may look frozen without being so.",
        "Without configured limits, physically impossible values are not detected.",
    ],
)
METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version="1.0.0",
    input_ports=[InputPort(port_id="pv", semantic_type="process_value", dtype="timeseries_float")],
    input_schema=ValueIntegrityInput,
    parameter_schema=ValueIntegrityParameters,
    output_ports=[OutputPort(port_id="frozen_fraction", semantic_type="ratio", dtype="float")],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)


def longest_constant_seconds(values: pd.Series) -> float:
    """Longest stretch, in seconds, over which consecutive samples kept one value."""

    if len(values) < 2:
        return 0.0
    numbers = values.to_numpy()
    times = pd.DatetimeIndex(values.index)
    starts = np.flatnonzero(np.r_[True, numbers[1:] != numbers[:-1]])
    ends = np.r_[starts[1:] - 1, len(numbers) - 1]
    return float((times[ends] - times[starts]).total_seconds().max())


def run(input_data: ValueIntegrityInput, parameters: ValueIntegrityParameters) -> MethodResult:
    dataset = input_data.dataset
    frame = raw_frame(dataset)
    span = window(dataset, frame)
    if "pv" not in frame.columns or span is None or frame["pv"].dropna().empty:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("No PV in the analysed window."), ["pv"]
        )
    start, end = span
    raw = frame["pv"].dropna()
    values = pd.to_numeric(raw, errors="coerce").replace([np.inf, -np.inf], np.nan)
    invalid = values.isna()
    if parameters.lower_limit is not None:
        invalid |= values < parameters.lower_limit
    if parameters.upper_limit is not None:
        invalid |= values > parameters.upper_limit
    invalid_fraction = float(invalid.mean())
    valid = values[~invalid].sort_index()
    frozen_fraction = longest_constant_seconds(valid) / max((end - start).total_seconds(), 1.0)
    reasons = []
    if invalid_fraction > parameters.invalid_fraction_limit:
        reasons.append(
            t("{fraction} of the PV samples are invalid", fraction=_pct(invalid_fraction))
        )
    if frozen_fraction > parameters.frozen_fraction_limit:
        reasons.append(
            t(
                "PV stuck at the same value for {fraction} of the window",
                fraction=_pct(frozen_fraction),
            )
        )
    apt = not reasons
    score = round(100.0 * max(invalid_fraction, frozen_fraction), 1)
    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=MethodStatus.OK if apt else MethodStatus.BAD,
        score=score,
        message=t("PV values are sound.") if apt else "; ".join(reasons) + ".",
        metrics={
            "apt": apt,
            "invalid_fraction": round(invalid_fraction, 4),
            "frozen_fraction": round(frozen_fraction, 4),
            "sample_count": int(len(raw)),
        },
    )
