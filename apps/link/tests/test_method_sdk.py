"""Methods written as one function with ``@method`` (from plantcraft_sdk), as LinkCraft uses it."""

from __future__ import annotations

import pandas as pd
import pytest
from plantcraft_sdk.methods import (
    Finding,
    LoopDataset,
    MethodStatus,
    NotEnoughData,
    method,
    param,
)
from pydantic import ValidationError


@method("demo_error", name="Demo error", describe="Mean error {mae:.2} ({inside:%} in band).")
def demo_error(
    pv,
    sp,
    op=None,
    *,
    tolerance: float = param(2.0, gt=0, help="Error for a score of 100."),
    sample_seconds,
):
    """Mean absolute error between PV and SP."""

    if len(pv) < 4:
        raise NotEnoughData("Window too short.")
    error = (pv - sp).abs()
    return Finding(
        score=100 * error.mean() / tolerance,
        metrics={
            "mae": error.mean(),
            "inside": (error < 1).mean(),
            "has_op": op is not None,
            "dt": sample_seconds,
        },
    )


def _dataset(**columns) -> LoopDataset:
    size = len(next(iter(columns.values())))
    data = pd.DataFrame(
        {"timestamp": pd.date_range("2026-01-01", periods=size, freq="60s"), **columns}
    )
    return LoopDataset(loop_id="FIC-1", data=data, sample_time_seconds=60)


def _run(block, dataset, **parameters):
    return block.run(block.input_schema(dataset=dataset), block.parameter_schema(**parameters))


def test_signature_becomes_the_method_contract():
    spec = demo_error.METHOD_SPEC
    assert [(port.port_id, port.required) for port in spec.input_ports] == [
        ("pv", True),
        ("sp", True),
        ("op", False),
    ]
    assert spec.metadata.required_signals == ["pv", "sp"]
    assert spec.metadata.description == "Mean absolute error between PV and SP."
    schema = spec.parameter_schema.model_json_schema()["properties"]["tolerance"]
    assert schema["default"] == 2.0 and schema["exclusiveMinimum"] == 0
    assert schema["description"] == "Error for a score of 100."
    with pytest.raises(ValidationError):
        spec.parameter_schema(tolerance=0)


def test_run_aligns_signals_and_scores_with_the_platform_convention():
    dataset = _dataset(pv=[1.0, 2.0, None, 4.0, 5.0], sp=[1.0, 1.0, 1.0, 1.0, 2.0])
    result = _run(demo_error, dataset, tolerance=4.0)

    assert result.status == MethodStatus.WARNING
    assert result.metrics["mae"] == pytest.approx(1.75)  # The gap row is dropped.
    assert result.metrics["has_op"] is False
    assert result.metrics["dt"] == 60
    assert result.score == pytest.approx(43.75)
    assert demo_error.describe(result.metrics) == "Mean error 1.75 (25% in band)."


def test_missing_signal_and_not_enough_data_are_insufficient_data():
    missing = _run(demo_error, _dataset(pv=[1.0, 2.0, 3.0, 4.0]))
    assert missing.status == MethodStatus.INSUFFICIENT_DATA
    assert missing.message == "Missing signals: SP."

    short = _run(demo_error, _dataset(pv=[1.0, 2.0, 3.0], sp=[1.0, 1.0, 1.0]))
    assert short.status == MethodStatus.INSUFFICIENT_DATA
    assert short.message == "Window too short."


def test_the_function_stays_callable_for_notebooks_and_tests():
    pv = pd.Series([1.0, 3.0])
    sp = pd.Series([1.0, 1.0])
    with pytest.raises(NotEnoughData):
        demo_error(pv, sp, sample_seconds=1)


def test_dict_results_and_bad_returns():
    @method("demo_dict", name="Dict")
    def demo_dict(pv):
        return {"score": 80, "metrics": {"n": len(pv)}}

    @method("demo_bad", name="Bad")
    def demo_bad(pv):
        return 42

    dataset = _dataset(pv=[1.0, 2.0, 3.0])
    assert _run(demo_dict, dataset).status == MethodStatus.BAD
    with pytest.raises(TypeError):
        _run(demo_bad, dataset)


def test_signal_with_a_value_default_is_rejected():
    with pytest.raises(TypeError):

        @method("demo_wrong", name="Wrong")
        def demo_wrong(pv, sp=1.0):
            return Finding(score=0)
