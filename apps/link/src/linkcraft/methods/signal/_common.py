"""Helpers the checks share: the signal's samples, its window, bands and events.

A check sees one signal as a ``LoopDataset`` whose ``raw`` frame holds the
samples exactly as PlantCraft recorded them (column ``value``; ``reference``
when the signal has a reference signal), indexed by naive UTC time, and whose
``metadata`` carries the signal's ``kind``, ``unit``, ``low`` and ``high``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from plantcraft_sdk.methods import LoopDataset

# Events kept per check and signal: enough to point at the problem, small enough to store.
MAX_EVENTS = 50


def samples(dataset: LoopDataset, column: str = "value") -> pd.Series:
    """The recorded samples of one column, sorted by time, one per instant."""

    frame = dataset.raw if dataset.raw is not None else pd.DataFrame()
    if column not in frame.columns:
        return pd.Series(dtype=float)
    values = frame[column].dropna()
    values = values[~values.index.isna()]
    values = values[~values.index.duplicated(keep="last")]
    return values.sort_index()


def numbers(dataset: LoopDataset, column: str = "value") -> pd.Series:
    """The finite numeric samples of one column (text and invalid values left out)."""

    values = pd.to_numeric(samples(dataset, column), errors="coerce")
    return values.replace([np.inf, -np.inf], np.nan).dropna().astype(float)


def is_text(dataset: LoopDataset) -> bool:
    return str(dataset.metadata.get("kind") or "number") == "text"


NOT_GOOD = ("uncertain", "substituted", "bad")


def quality_spans(
    dataset: LoopDataset, start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] | None:
    """Where in ``[start, end]`` the source said the samples were not good, per quality
    (``uncertain``, ``substituted``, ``bad``); None when the source keeps no quality.

    Each change in ``metadata["quality"]`` (``[{t, quality}]``) holds until the next one.
    """

    changes = (dataset.metadata or {}).get("quality")
    if changes is None:
        return None
    marks = sorted((_naive(item["t"]), str(item.get("quality") or "good")) for item in changes)
    spans: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = {code: [] for code in NOT_GOOD}
    for position, (at, code) in enumerate(marks):
        until = marks[position + 1][0] if position + 1 < len(marks) else end
        begin, finish = max(at, start), min(until, end)
        if code in spans and finish > begin:
            spans[code].append((begin, finish))
    return spans


def window(dataset: LoopDataset) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """The checked window ``[start, end]`` (naive UTC), else the samples' own span."""

    start = _naive(dataset.start_time) if dataset.start_time else None
    end = _naive(dataset.end_time) if dataset.end_time else None
    if start is None or end is None:
        values = samples(dataset)
        if len(values) < 2:
            return None
        start, end = values.index.min(), values.index.max()
    return (start, end) if end > start else None


def _naive(value: object) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def limits(dataset: LoopDataset) -> tuple[float | None, float | None]:
    """The signal's engineering limits, when known and sensible."""

    def number(key: str) -> float | None:
        value = dataset.metadata.get(key)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if np.isfinite(value) else None

    low, high = number("low"), number("high")
    if low is not None and high is not None and high <= low:
        return None, None
    return low, high


def robust_span(values: pd.Series) -> float:
    """The 1st to 99th percentile range: the signal's spread without its outliers."""

    if values.empty:
        return 0.0
    low, high = np.nanpercentile(values.to_numpy(), [1, 99])
    return float(high - low)


def score_band(badness: float, warn: float, bad: float, worst: float | None = None) -> float:
    """0 to 100 so that ``warn`` scores 25 (warning) and ``bad`` 75 (bad).

    Statuses follow the SDK's convention: a score from 25 is a warning and from
    75 a bad result, so the score and the status a check reports always agree.
    """

    if not np.isfinite(badness) or badness <= 0:
        return 0.0
    worst = worst if worst is not None and worst > bad else bad * 2
    if badness < warn:
        return 25.0 * badness / warn
    if badness < bad:
        return 25.0 + 50.0 * (badness - warn) / (bad - warn)
    return min(100.0, 75.0 + 25.0 * (badness - bad) / (worst - bad))


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """``(first, last)`` positions of every stretch where ``mask`` is true."""

    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return []
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1) - 1
    return list(zip(starts.tolist(), ends.tolist(), strict=True))


def iso(stamp: pd.Timestamp) -> str:
    return pd.Timestamp(stamp).tz_localize("UTC").isoformat()


def event(start: pd.Timestamp, end: pd.Timestamp, label: str, **details: object) -> dict:
    """One finding in time, as ``Finding.events`` takes it (UTC ISO times)."""

    return {"start_time": iso(start), "end_time": iso(end), "label": label, "details": details}


def worst_events(items: list[tuple[float, dict]]) -> list[dict]:
    """The ``MAX_EVENTS`` largest events (by their weight), in time order."""

    chosen = sorted(items, key=lambda item: item[0], reverse=True)[:MAX_EVENTS]
    return [item for _weight, item in sorted(chosen, key=lambda item: item[1]["start_time"])]


def num(value: object) -> str:
    """A number for a sentence: four significant figures, no scientific notation for plain sizes."""

    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        return str(value)
    number = float(value)
    if not np.isfinite(number):
        return "—"
    if number == int(number) and abs(number) < 1e6:
        return str(int(number))
    text = f"{number:.4g}"
    return text if "e" not in text else f"{number:.3e}"


def spread(values: np.ndarray) -> float:
    """A robust standard deviation: 1.4826 MAD, or the 10-90 percentile range / 2.56 when one
    value holds most samples (MAD is then zero although the signal moves)."""

    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return 0.0
    mad = 1.4826 * float(np.median(np.abs(values - np.median(values))))
    low, high = np.percentile(values, [10, 90])
    return max(mad, float(high - low) / 2.56)
