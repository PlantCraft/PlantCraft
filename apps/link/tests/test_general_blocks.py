"""The general blocks: signal treatment, math and conditions, statistics, the operating window
and equipment (``blocks/transforms.py``, ``conditions.py``, ``stats.py``, ``equipment.py``)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.blocks import Context, NoData, check_block
from pydantic import ValidationError

from linkcraft.blocks import compile_algorithm
from linkcraft.blocks.catalog import CATALOG
from linkcraft.blocks.transforms import convert

STEP = 10.0
INDEX = pd.date_range("2026-10-22 08:00", periods=361, freq="10s")
GENERAL = [
    block_id
    for block_id in CATALOG
    if block_id.split(".")[0] in ("stats", "equipment")
    or block_id
    in (
        "transform.derivative",
        "transform.resample",
        "transform.expression",
        "transform.unit",
        "transform.select",
        "transform.operation_filter",
        "logic.compare",
        "logic.combine",
    )
]


def run(block_id: str, inputs: dict, **parameters) -> dict:
    block = CATALOG[block_id]
    return block.run(inputs, block.spec.parameters(**parameters), Context(sample_seconds=STEP))


def series(values) -> pd.Series:
    return pd.Series(np.asarray(values, dtype=float), index=INDEX[: len(values)])


def test_every_general_block_keeps_the_contract_and_cites_its_sources():
    assert len(GENERAL) == 17
    for block_id in GENERAL:
        spec = CATALOG[block_id].spec
        assert check_block(spec) == [], block_id
    cited = [b for b in GENERAL if b.split(".")[0] in ("stats", "equipment")]
    assert all(CATALOG[b].spec.docs.references for b in cited)


# Signal treatment ---------------------------------------------------------------------------


def test_derivative_is_a_rate_per_the_chosen_time():
    ramp = series(np.arange(361) * 0.5)  # 0.5 per 10 s
    assert run("transform.derivative", {"x": ramp}, per="min")["value"].iloc[1:].eq(3.0).all()
    assert run("transform.derivative", {"x": ramp}, per="s")["value"].iloc[5] == 0.05


def test_resample_holds_each_periods_value_on_the_grid():
    x = series(np.arange(361))
    found = run("transform.resample", {"x": x}, period_seconds=600, how="mean")["value"]
    assert len(found) == len(x) and found.iloc[0] == 29.5 and found.iloc[59] == 29.5
    assert found.iloc[60] == 89.5
    assert run("transform.resample", {"x": x}, period_seconds=600, how="max")["value"].iloc[0] == 59


# Math and conditions ------------------------------------------------------------------------


def test_expression_computes_a_safe_formula():
    a, b, c = series([2, 4, 6]), series([3, 3, 3]), series([1, 2, 0])
    found = run("transform.expression", {"a": a, "b": b, "c": c}, expression="a * b / c")["value"]
    assert found.iloc[:2].tolist() == [6.0, 6.0] and np.isnan(found.iloc[2])
    found = run("transform.expression", {"a": a}, expression="max(a, 3) + sqrt(4) ** 2")["value"]
    assert found.tolist() == [7.0, 8.0, 10.0]
    with pytest.raises(ValueError, match="not wired"):
        run("transform.expression", {"a": a}, expression="a + d")
    for bad in ("__import__('os')", "a.real", "open('x')", "a if b else c", "[a]", "a +"):
        with pytest.raises(ValidationError):
            CATALOG["transform.expression"].spec.parameters(expression=bad)


def test_engineering_units_convert_within_a_quantity():
    assert convert(1.0, "bar", "kPa") == pytest.approx(100.0)
    assert convert(0.0, "°C", "°F") == pytest.approx(32.0)
    assert convert(100.0, "°C", "K") == pytest.approx(373.15)
    assert convert(36.0, "t/h", "kg/s") == pytest.approx(10.0)
    assert convert(1.0, "US gal/min", "m³/h") == pytest.approx(0.2271247)
    found = run("transform.unit", {"x": series([1, 2])}, from_unit="bar", to_unit="psi")["value"]
    assert found.iloc[0] == pytest.approx(14.5038, rel=1e-4)
    with pytest.raises(ValidationError, match="pressure"):
        CATALOG["transform.unit"].spec.parameters(from_unit="bar", to_unit="°C")


def test_compare_with_a_deadband_and_combine():
    x = series([0, 6, 4.5, 6, 3, 2])
    plain = run("logic.compare", {"x": x}, operator=">", limit=5)["intervals"]
    assert plain.tolist() == [False, True, False, True, False, False]
    held = run("logic.compare", {"x": x}, operator=">", limit=5, deadband=1)["intervals"]
    assert held.tolist() == [False, True, True, True, False, False]
    other = series([1, 1, 0, 0, 1, 1]) > 0
    both = run("logic.combine", {"in": [plain, other]}, mode="and")["intervals"]
    assert both.tolist() == [False, True, False, False, False, False]
    either = run("logic.combine", {"in": [plain, other]}, mode="or", invert=True)["intervals"]
    assert either.tolist() == [False, False, True, False, False, False]


def test_select_by_condition():
    a, b = series([1, 2, 3]), series([10, 20, 30])
    when = pd.Series([True, False, True], index=a.index)
    assert run("transform.select", {"when": when, "a": a, "b": b})["value"].tolist() == [1, 20, 3]
    alone = run("transform.select", {"when": when, "a": a, "b": None})["value"]
    assert np.isnan(alone.iloc[1])


# Operating window ---------------------------------------------------------------------------


def test_only_in_operation_drops_start_up_and_shutdown():
    x = series(np.ones(361))
    running = pd.Series(False, index=INDEX)
    running.iloc[60:300] = True  # starts at 10 min, stops after 50 min
    found = run(
        "transform.operation_filter",
        {"x": x, "running": running},
        after_start_seconds=600,
        before_stop_seconds=300,
    )
    steady = found["intervals"]
    assert steady.iloc[:120].sum() == 0 and steady.iloc[120] and not steady.iloc[270]
    assert steady.iloc[269] and steady.sum() == 150  # samples 120 to 269
    assert found["value"].notna().sum() == steady.sum()
    # A run already going when the window starts is not cut there.
    running[:] = True
    assert run("transform.operation_filter", {"x": x, "running": running}, after_start_seconds=600)[
        "intervals"
    ].all()


def test_time_outside_limits():
    x = series([1, 5, 5, 1, 1, 9, 1, 1, 1, 1])
    found = run("stats.outside_limits", {"x": x, "when": None}, lower=0, upper=4)
    assert found["share"] == pytest.approx(30.0) and found["minutes"] == pytest.approx(0.5)
    when = pd.Series([True] * 5 + [False] * 5, index=x.index)
    assert run("stats.outside_limits", {"x": x, "when": when}, upper=4)["share"] == 40.0
    with pytest.raises(ValidationError):
        CATALOG["stats.outside_limits"].spec.parameters()


# Statistics ---------------------------------------------------------------------------------


def test_location_and_spread_only_where_counted():
    x = series([1, 2, 3, 4, 100])
    when = pd.Series([True, True, True, True, False], index=x.index)
    assert run("stats.mean", {"x": x, "when": when})["value"] == 2.5
    assert run("stats.std", {"x": x, "when": None})["value"] == pytest.approx(np.std(x, ddof=1))
    assert run("stats.percentile", {"x": x, "when": None}, percent=50)["value"] == 3.0
    assert isinstance(run("stats.mean", {"x": series([np.nan, 1]), "when": None})["value"], NoData)


def test_histogram_keeps_the_bins_and_says_where_values_lie():
    rng = np.random.default_rng(1)
    x = series(np.r_[rng.normal(10, 1, 300), rng.normal(20, 1, 61)])
    found = run("stats.histogram", {"x": x, "when": None})
    detail = found["result"].detail
    assert sum(detail["counts"]) == 361 and len(detail["edges"]) == len(detail["counts"]) + 1
    assert found["result"].status == "ok" and "Half of the 361 samples" in found["result"].message
    assert 8 < found["mode"] < 12


def test_correlation_finds_the_lag():
    rng = np.random.default_rng(2)
    a = series(rng.normal(size=361).cumsum())
    b = a.shift(3)  # B trails A by 30 s
    found = run("stats.correlation", {"a": a, "b": b, "when": None}, max_lag_seconds=120)
    assert found["r"] == pytest.approx(1.0) and found["lag"] == -30.0
    flat = run("stats.correlation", {"a": a, "b": series(np.ones(361)), "when": None})
    assert isinstance(flat["r"], NoData)


def test_step_changes_are_found_once_each():
    rng = np.random.default_rng(3)
    values = rng.normal(0, 0.1, 361)
    values[150:] += 5.0
    values[280:] -= 2.0
    found = run("stats.steps", {"x": series(values)}, window_samples=10, sigmas=5)
    assert found["count"] == 2 and found["largest"] == pytest.approx(5.0, abs=0.2)
    assert list(np.flatnonzero(found["intervals"])) == [149, 279]
    quiet = run("stats.steps", {"x": series(rng.normal(0, 0.1, 361))}, window_samples=10)
    assert quiet["count"] == 0


# Equipment ----------------------------------------------------------------------------------


def test_heat_exchanger_ua_by_the_log_mean_difference():
    n = 4
    inputs = {
        "hot_in": series([150] * n),
        "hot_out": series([100] * n),
        "cold_in": series([30] * n),
        "cold_out": series([90, 90, 90, 160]),
        "flow": series([2] * n),
    }
    found = run("equipment.heat_exchanger", inputs, cp=4.18, clean_ua=10.0)
    duty = 2 * 4.18 * 60
    lmtd = (60 - 70) / np.log(60 / 70)
    assert found["duty"].iloc[0] == pytest.approx(duty)
    assert found["ua"].iloc[0] == pytest.approx(duty / lmtd)
    assert np.isnan(found["ua"].iloc[3])  # a temperature cross gives no UA
    assert found["ratio"] == pytest.approx(100 * duty / lmtd / 10.0)
    assert isinstance(run("equipment.heat_exchanger", inputs)["ratio"], NoData)


def test_pump_efficiency_against_its_curve():
    inputs = {"flow": series([100, 100, 0]), "dp": series([5, 5, 5]), "power": series([25, 0, 5])}
    found = run("equipment.pump", inputs, min_flow=10)
    assert found["efficiency"].iloc[0] == pytest.approx(100 * (100 / 3600 * 5 * 100) / 25)
    assert found["efficiency"].iloc[1:].isna().all()
    assert found["gap"].iloc[0] == pytest.approx(75 - 55.5556, abs=1e-3)
    assert found["mean_gap"] == pytest.approx(found["gap"].iloc[0])
    with pytest.raises(ValidationError, match="increase"):
        CATALOG["equipment.pump"].spec.parameters(curve=[[10, 50], [5, 60]])


# In a diagram -------------------------------------------------------------------------------


def test_the_blocks_wire_into_an_algorithm():
    def node(node_id, block, **parameters):
        return {"id": node_id, "block": block, "parameters": parameters, "x": 0, "y": 0}

    def edge(source, port, target, target_port):
        return {"source": source, "source_port": port, "target": target, "target_port": target_port}

    diagram = {
        "version": "1.0",
        "nodes": [
            node("pv", "input.signal", role="pv"),
            node("op", "input.signal", role="op"),
            node("running", "logic.compare", operator=">", limit=5),
            node("steady", "transform.operation_filter"),
            node("mean", "stats.mean"),
            node("out", "stats.outside_limits", upper=80),
            node("judge", "logic.limits", warning=5, bad=20),
            node("result", "output.result", name="Time above 80"),
        ],
        "edges": [
            edge("op", "value", "running", "x"),
            edge("pv", "value", "steady", "x"),
            edge("running", "intervals", "steady", "running"),
            edge("steady", "value", "mean", "x"),
            edge("pv", "value", "out", "x"),
            edge("steady", "intervals", "out", "when"),
            edge("out", "share", "judge", "x"),
            edge("judge", "result", "result", "in"),
        ],
    }
    assert compile_algorithm(diagram).errors == []
