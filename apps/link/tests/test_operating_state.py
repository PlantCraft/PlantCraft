from __future__ import annotations

import numpy as np
import pandas as pd

from linkcraft.loops.analysis import _operating_state


def _frame(pv: float, sp: float, op: float) -> pd.DataFrame:
    n = 200
    noise = np.random.default_rng(1).normal(0, 0.5, n)
    return pd.DataFrame({"pv": pv + noise, "sp": np.full(n, sp), "op": np.full(n, op)})


def test_output_pinned_with_pv_off_target_is_a_saturated_active_loop():
    assert _operating_state(_frame(pv=40.0, sp=50.0, op=100.0))[0] == "active"


def test_output_pinned_with_a_dead_pv_is_possibly_inactive():
    frame = _frame(pv=40.0, sp=50.0, op=0.0)
    frame["pv"] = 40.0
    assert _operating_state(frame)[0] == "possibly_inactive"


def test_output_pinned_with_pv_on_target_is_possibly_inactive():
    assert _operating_state(_frame(pv=50.0, sp=50.0, op=100.0))[0] == "possibly_inactive"
