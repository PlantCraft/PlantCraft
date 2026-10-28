"""Bad data never crashes: every method, fed with junk (the API routes: tests/test_suite_rules.py).

A method facing NaN, gaps, constant or empty signals, infinities, shuffled or
duplicated timestamps must return a ``MethodResult`` (insufficient data, not
applicable or a finding), never raise.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.methods import LoopDataset, MethodResult

from linkcraft.catalog.registry import METHOD_MODULES

N = 120


def _frame(**columns) -> pd.DataFrame:
    length = max((len(value) for value in columns.values()), default=0)
    data = {"timestamp": pd.date_range("2026-01-01", periods=length, freq="10s")}
    data.update(columns)
    return pd.DataFrame(data)


def _loop(pv, sp=None, op=None, mode=None) -> dict:
    n = len(pv)
    return {
        "pv": pv,
        "sp": np.full(n, 50.0) if sp is None else sp,
        "op": np.full(n, 40.0) if op is None else op,
        "mode": np.array(["auto"] * n, dtype=object) if mode is None else mode,
        "neighbor_pv": np.linspace(0, 1, n),
    }


def _hostile_frames() -> dict[str, pd.DataFrame]:
    ramp = np.linspace(40, 60, N)
    nan = np.full(N, np.nan)
    spikes = ramp.copy()
    spikes[::7] = 1e12
    infinite = ramp.copy()
    infinite[5:15] = np.inf
    infinite[20:25] = -np.inf
    gappy = ramp.copy()
    gappy[10:100] = np.nan
    frames = {
        "empty": pd.DataFrame(
            {"timestamp": pd.to_datetime([]), "pv": [], "sp": [], "op": [], "mode": []}
        ),
        "one_row": _frame(**_loop(np.array([50.0]))),
        "two_rows": _frame(**_loop(np.array([50.0, 51.0]))),
        "all_nan": _frame(**_loop(nan, sp=nan, op=nan)),
        "constant": _frame(**_loop(np.full(N, 50.0))),
        "spikes": _frame(**_loop(spikes)),
        "infinities": _frame(**_loop(infinite, op=infinite)),
        "mostly_gaps": _frame(**_loop(gappy)),
        "negative_huge": _frame(**_loop(-1e15 * np.ones(N))),
        "garbage_mode": _frame(
            **_loop(ramp, mode=np.array(["?", None, 3, "MAN"] * (N // 4), dtype=object))
        ),
        "pv_only": _frame(pv=ramp),
        "no_signals": _frame(other=ramp),
    }
    shuffled = _frame(**_loop(ramp)).sample(frac=1.0, random_state=1).reset_index(drop=True)
    frames["shuffled_time"] = shuffled
    duplicated = _frame(**_loop(ramp))
    duplicated["timestamp"] = duplicated["timestamp"].iloc[0]
    frames["same_timestamp"] = duplicated
    return frames


FRAMES = _hostile_frames()


def _inputs(spec, dataset):
    fields = getattr(spec.input_schema, "model_fields", {})
    values = {"dataset": dataset}
    if "secondary_column" in fields:
        values["secondary_column"] = "neighbor_pv"
    return spec.input_schema(**values)


@pytest.mark.parametrize("frame_name", sorted(FRAMES))
@pytest.mark.parametrize("method_id", sorted(METHOD_MODULES))
def test_methods_survive_hostile_data(method_id, frame_name):
    module = METHOD_MODULES[method_id]
    spec = module.METHOD_SPEC
    frame = FRAMES[frame_name].copy()
    dataset = LoopDataset(
        loop_id="FIC-HOSTILE",
        data=frame,
        sample_time_seconds=10.0,
        raw=frame.set_index("timestamp") if "timestamp" in frame else None,
    )
    result = module.run(_inputs(spec, dataset), spec.parameter_schema())
    assert isinstance(result, MethodResult)
    assert math.isfinite(result.score) and 0 <= result.score <= 100
    # The finding wording must also survive whatever metrics came back.
    describe = getattr(module, "describe", None)
    if describe is not None:
        assert isinstance(describe(result.metrics), str)
