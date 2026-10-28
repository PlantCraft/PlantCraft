"""Turn sparse recorded samples into the regular loop frame the methods expect."""

from __future__ import annotations

import pandas as pd

from linkcraft.config import LoopConfig

EMPTY_COLUMNS = ["timestamp", "pv", "sp", "op", "mode"]


def regular_series(
    raw: pd.DataFrame,
    column: str | None,
    grid: pd.DatetimeIndex,
    *,
    step: bool,
) -> pd.Series:
    """One signal on the grid: held between changes (``step``) or interpolated in time.

    Nothing is invented outside the recorded span: before the first sample (and,
    for interpolated signals, after the last) the value stays empty.
    """

    if not column or column not in raw.columns:
        return pd.Series(index=grid, dtype=float)

    values = raw[column]
    if step:
        clean = values.dropna()
    else:
        clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return pd.Series(index=grid, dtype=float)

    clean = clean.loc[~clean.index.duplicated(keep="last")].sort_index()
    union = clean.index.union(grid)
    expanded = clean.reindex(union).sort_index()
    if step:
        regular = expanded.ffill().reindex(grid)
    else:
        regular = expanded.interpolate(method="time", limit_area="inside").reindex(grid)
    regular = regular.where(grid >= clean.index.min())
    if not step:
        regular = regular.where(grid <= clean.index.max())
    return regular


def build_loop_frame(raw: pd.DataFrame, loop: LoopConfig, sample_seconds: int) -> pd.DataFrame:
    """Convert sparse, wide recorded data into one regular semantic loop frame.

    ``raw`` is indexed by time (naive UTC) with one column per signal id. The
    frame has ``timestamp`` plus ``pv``, ``sp``, ``op``, ``mode`` and, when the
    loop has one, ``secondary``.
    """

    if raw.empty:
        return pd.DataFrame(columns=EMPTY_COLUMNS)
    start = raw.index.min().ceil(f"{sample_seconds}s")
    end = raw.index.max().floor(f"{sample_seconds}s")
    if start > end:
        return pd.DataFrame(columns=EMPTY_COLUMNS)
    grid = pd.date_range(start, end, freq=f"{sample_seconds}s")
    signals = loop.signals

    frame = pd.DataFrame(index=grid)
    frame["timestamp"] = grid
    frame["pv"] = regular_series(raw, signals.pv, grid, step=False)
    frame["sp"] = regular_series(raw, signals.sp, grid, step=True)
    frame["op"] = regular_series(raw, signals.op, grid, step=False)
    if signals.mode:
        frame["mode"] = regular_series(raw, signals.mode, grid, step=True)
    if signals.secondary:
        frame["secondary"] = regular_series(raw, signals.secondary, grid, step=False)
    return frame.reset_index(drop=True)


def semantic_raw(raw: pd.DataFrame, loop: LoopConfig) -> pd.DataFrame:
    """The loop's raw samples, with columns named pv, sp, op, mode, secondary."""

    columns = {
        name: raw[column]
        for name, column in loop.signals.model_dump().items()
        if isinstance(column, str) and column in raw.columns
    }
    return pd.DataFrame(columns, index=raw.index)


def loop_signal_ids(loop: LoopConfig) -> list[str]:
    """The signal ids behind one loop, in role order, without repeats."""

    return list(
        dict.fromkeys(
            column
            for column in loop.signals.model_dump().values()
            if isinstance(column, str) and column
        )
    )
