"""Helpers shared by the data quality methods."""

from __future__ import annotations

import numpy as np
import pandas as pd
from plantcraft_sdk.methods import LoopDataset

SIGNALS = ("pv", "sp", "op")


def raw_frame(dataset: LoopDataset) -> pd.DataFrame:
    """Raw samples when the caller supplied them, else the regular frame."""

    if dataset.raw is not None:
        return dataset.raw
    frame = dataset.data
    if "timestamp" in frame:
        frame = frame.set_index(pd.to_datetime(frame["timestamp"], errors="coerce"))
    return frame


def window(dataset: LoopDataset, frame: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    start = pd.Timestamp(dataset.start_time) if dataset.start_time else None
    end = pd.Timestamp(dataset.end_time) if dataset.end_time else None
    if start is None or end is None:
        if frame.empty:
            return None
        start, end = frame.index.min(), frame.index.max()
    return (start, end) if end > start else None


def numeric(values: pd.Series) -> pd.Series:
    clean = pd.to_numeric(values, errors="coerce")
    return clean.replace([np.inf, -np.inf], np.nan).dropna()


def present_signals(frame: pd.DataFrame) -> list[str]:
    return [name for name in SIGNALS if name in frame.columns and frame[name].notna().any()]
