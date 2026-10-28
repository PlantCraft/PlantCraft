"""Utilities shared by methodology implementations."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from plantcraft_sdk.i18n import t
from plantcraft_sdk.methods.contracts import (
    EvidenceItem,
    LoopDataset,
    MethodEvent,
    MethodMetadata,
    MethodResult,
    MethodStatus,
    ScientificReference,
    Severity,
)


def missing_columns(dataset: LoopDataset, columns: Iterable[str]) -> list[str]:
    return [column for column in columns if column not in dataset.data.columns]


def numeric_frame(dataset: LoopDataset, columns: Iterable[str]) -> pd.DataFrame:
    frame = pd.DataFrame(index=dataset.data.index)
    for column in columns:
        frame[column] = pd.to_numeric(dataset.data[column], errors="coerce")
    return frame.replace([np.inf, -np.inf], np.nan).dropna()


def numeric_series(dataset: LoopDataset, column: str) -> pd.Series:
    values = pd.to_numeric(dataset.data[column], errors="coerce")
    return values.replace([np.inf, -np.inf], np.nan).dropna()


def estimate_sample_seconds(dataset: LoopDataset, valid_index: pd.Index | None = None) -> float:
    if dataset.sample_time_seconds and dataset.sample_time_seconds > 0:
        return float(dataset.sample_time_seconds)
    if "timestamp" not in dataset.data.columns:
        return 1.0
    frame = dataset.data if valid_index is None else dataset.data.loc[valid_index]
    timestamps = pd.to_datetime(frame["timestamp"], errors="coerce").dropna().sort_values()
    if len(timestamps) < 2:
        return 1.0
    diffs = timestamps.diff().dropna().dt.total_seconds()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return 1.0
    return float(diffs.median())


def duration_hours(dataset: LoopDataset, valid_index: pd.Index | None = None) -> float:
    frame = dataset.data if valid_index is None else dataset.data.loc[valid_index]
    if len(frame) < 2:
        return 0.0
    return max(estimate_sample_seconds(dataset, frame.index) * (len(frame) - 1) / 3600.0, 0.0)


def severity_from_score(score: float) -> Severity:
    if score >= 75:
        return Severity.CRITICAL
    if score >= 50:
        return Severity.HIGH
    if score >= 25:
        return Severity.MEDIUM
    return Severity.LOW


def status_from_score(score: float) -> MethodStatus:
    if score >= 75:
        return MethodStatus.BAD
    if score >= 25:
        return MethodStatus.WARNING
    return MethodStatus.OK


def clamp_score(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return float(min(100.0, max(0.0, value)))


def normalized_score(value: float, reference: float) -> float:
    if reference <= 0:
        return 0.0
    return clamp_score(100.0 * value / reference)


def result(
    metadata: MethodMetadata,
    loop_id: str,
    status: MethodStatus,
    score: float,
    message: str,
    metrics: dict[str, float | int | str | bool | None] | None = None,
    events: list[MethodEvent] | None = None,
    evidence: list[EvidenceItem] | None = None,
    limitations: list[str] | None = None,
    references: list[ScientificReference] | None = None,
) -> MethodResult:
    safe_score = clamp_score(score)
    severity = (
        Severity.LOW
        if status in {MethodStatus.INSUFFICIENT_DATA, MethodStatus.NOT_APPLICABLE}
        else severity_from_score(safe_score)
    )
    return MethodResult(
        method_id=metadata.method_id,
        loop_id=loop_id,
        status=status,
        score=safe_score,
        severity=severity,
        message=message,
        metrics=metrics or {},
        events=events or [],
        evidence=evidence or [],
        references=references or metadata.references,
        limitations=[*(t(item) for item in metadata.limitations), *(limitations or [])],
    )


def insufficient_data(
    metadata: MethodMetadata, loop_id: str, message: str, missing: list[str] | None = None
) -> MethodResult:
    evidence = []
    if missing:
        evidence.append(
            EvidenceItem(
                label="missing_signals",
                value=", ".join(missing),
                description="Required input signals were not available in the LoopDataset.",
            )
        )
    return result(
        metadata=metadata,
        loop_id=loop_id,
        status=MethodStatus.INSUFFICIENT_DATA,
        score=0.0,
        message=message,
        evidence=evidence,
    )


def autocorrelation_peak(
    values: np.ndarray, min_lag: int = 2, max_lag: int | None = None
) -> tuple[float, int | None]:
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size < max(min_lag + 2, 8):
        return 0.0, None
    clean = clean - np.mean(clean)
    std = float(np.std(clean))
    if std <= 0:
        return 0.0, None
    corr = np.correlate(clean, clean, mode="full")[clean.size - 1 :]
    if corr[0] == 0:
        return 0.0, None
    corr = corr / corr[0]
    upper = max_lag if max_lag is not None else clean.size // 2
    upper = min(max(upper, min_lag + 1), clean.size)
    segment = corr[min_lag:upper]
    if segment.size < 3:
        return 0.0, None

    # A high value at the first allowed lag is common in smooth or trending
    # signals and is not, by itself, evidence of an oscillatory period.  Keep
    # only genuine local maxima after lag zero.
    local_offsets = (
        np.flatnonzero(
            (segment[1:-1] > segment[:-2]) & (segment[1:-1] >= segment[2:]) & (segment[1:-1] > 0)
        )
        + 1
    )
    if local_offsets.size == 0:
        return 0.0, None
    best_offset = int(local_offsets[np.argmax(segment[local_offsets])])
    lag = min_lag + best_offset
    return float(segment[best_offset]), lag


def count_reversals(values: np.ndarray, epsilon: float = 1e-9) -> int:
    diffs = np.diff(np.asarray(values, dtype=float))
    diffs = diffs[np.abs(diffs) > epsilon]
    if diffs.size < 2:
        return 0
    signs = np.sign(diffs)
    return int(np.sum(signs[1:] != signs[:-1]))
