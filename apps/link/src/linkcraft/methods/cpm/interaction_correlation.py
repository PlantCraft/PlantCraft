"""Cross-correlation screening between two process signals."""

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

from linkcraft.methods.references import (
    BAUER_2016_CPM_SURVEY,
    THORNHILL_HAGGLUND_1997_OSCILLATION,
)


class InteractionCorrelationInput(BaseModel):
    dataset: LoopDataset
    primary_column: str = "pv"
    secondary_column: str = "secondary"


class InteractionCorrelationParameters(BaseModel):
    max_lag_samples: int = Field(default=60, ge=0)
    correlation_threshold: float = Field(default=0.50, gt=0.0, le=1.0)


METHOD_METADATA = MethodMetadata(
    method_id="interaction_cross_correlation",
    name="Cross-correlation interaction screening",
    description="Whether this loop's error moves together with another loop's: interaction.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY, THORNHILL_HAGGLUND_1997_OSCILLATION],
    required_signals=["pv", "secondary_signal"],
    implemented_formula="Compute maximum absolute Pearson correlation across positive and negative lags; score=max_abs_corr/correlation_threshold.",
    assumptions=["The secondary signal is aligned to the same time base as the primary signal."],
    limitations=[
        "Correlation does not prove causation; common disturbances and the "
        "process topology must be reviewed."
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(
            port_id="pv", semantic_type="process_variable", dtype="timeseries_float", required=True
        ),
        InputPort(
            port_id="secondary",
            semantic_type="timeseries_signal",
            dtype="timeseries_float",
            required=True,
        ),
    ],
    input_schema=InteractionCorrelationInput,
    parameter_schema=InteractionCorrelationParameters,
    output_ports=[
        OutputPort(port_id="max_abs_correlation", semantic_type="correlation", dtype="float"),
        OutputPort(
            port_id="best_lag_seconds", semantic_type="time_lag", dtype="float", unit="seconds"
        ),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def _corr_at_lag(x: np.ndarray, y: np.ndarray, lag: int) -> float:
    if lag < 0:
        xs = x[-lag:]
        ys = y[: len(y) + lag]
    elif lag > 0:
        xs = x[: len(x) - lag]
        ys = y[lag:]
    else:
        xs = x
        ys = y
    if len(xs) < 3 or len(ys) < 3:
        return 0.0
    if np.std(xs) <= 1e-12 or np.std(ys) <= 1e-12:
        return 0.0
    return float(np.corrcoef(xs, ys)[0, 1])


def run(
    input_data: InteractionCorrelationInput, parameters: InteractionCorrelationParameters
) -> MethodResult:
    dataset = input_data.dataset
    columns = [input_data.primary_column, input_data.secondary_column]
    missing = missing_columns(dataset, columns)
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("Both primary and secondary signals are required for interaction screening."),
            missing,
        )

    frame = numeric_frame(dataset, columns)
    if len(frame) < 3:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("Signals need at least three aligned numeric samples."),
        )

    x = frame[input_data.primary_column].to_numpy(dtype=float)
    y = frame[input_data.secondary_column].to_numpy(dtype=float)
    max_lag = min(parameters.max_lag_samples, len(frame) - 3)
    candidates = []
    for lag in range(-max_lag, max_lag + 1):
        corr = _corr_at_lag(x, y, lag)
        candidates.append((abs(corr), corr, lag))
    best_abs, best_corr, best_lag = max(candidates, key=lambda item: item[0])
    dt = estimate_sample_seconds(dataset, frame.index)
    score = normalized_score(best_abs, parameters.correlation_threshold)
    secondary_column = input_data.secondary_column

    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Cross-correlation interaction screening completed."),
        metrics={
            "primary_column": input_data.primary_column,
            "secondary_column": secondary_column,
            "max_abs_correlation": float(best_abs),
            "signed_correlation": float(best_corr),
            "best_lag_samples": int(best_lag),
            "best_lag_seconds": float(best_lag * dt),
            "valid_samples": int(len(frame)),
        },
        limitations=[
            t(
                "The correlation with {signal} is only a screening and requires "
                "a review of the process topology.",
                signal=secondary_column,
            )
        ],
    )


def describe(metrics: dict) -> str:
    return t(
        "Correlation of {correlation} with the secondary signal, with a lag of {lag} min.",
        correlation=_n(metrics.get("signed_correlation")),
        lag=_n(float(metrics.get("best_lag_seconds") or 0) / 60),
    )
