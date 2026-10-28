"""Calibrate and PlantCraft Twin's twins as algorithms: a deviation block's calibration learned
on a period of normal operation (``assets.calibrate``), runs laid end to end over a period with
one read of the plant (``assets.run.runs_over``), and a twin's fields as a diagram
(``assets.twins``)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from linkcraft.assets.calibrate import calibrate_on_asset, judged_part
from linkcraft.assets.run import AssetTiming, run_on_asset, runs_over, segment_ends
from linkcraft.assets.twins import twin_diagram, twin_subject, twin_timing
from linkcraft.blocks import compile_algorithm
from linkcraft.blocks.algorithms import BY_ID, UNIT_TWIN
from linkcraft.models.builtin import builtin_folder, builtin_models
from tests.conftest import client_for
from tests.plant import NOW, sid
from tests.test_asset_algorithms import STEP, TIMING, UNIT, unit_fake, unit_runtime
from tests.test_asset_algorithms import twin_diagram as unit_diagram

HOUR = pd.Timedelta(hours=1)
LOOP_INFO = next(
    item for item in builtin_models() if item["model_id"] == "plantcrafttwin-loopprocess"
)["info"]


@pytest.fixture
def runtime(tmp_path):
    rt = unit_runtime(tmp_path, unit_fake(bias=1.5))
    yield rt
    rt.shutdown()


def _calibrate(runtime, diagram, start, end, node="dev"):
    return calibrate_on_asset(
        diagram,
        node,
        UNIT,
        client=runtime.service_client,
        start=start,
        end=end,
        timing=AssetTiming.model_validate(TIMING),
        models=runtime.model_runtime(),
    )


def test_calibrate_learns_normal_operation_and_the_block_then_judges(runtime):
    start = pd.Timestamp(NOW) - 2 * HOUR + pd.Timedelta(minutes=30)
    found = _calibrate(runtime, unit_diagram(), start, start + HOUR)
    # One run per judged part (ten minutes), end to end over the hour.
    assert found["runs"] == 6 and found["used"] == 6 and found["skipped"] == 0
    calibration = found["calibration"]
    assert calibration["outputs"] == ["y"] and found["samples"] >= 600
    assert abs(calibration["mean"][0]) < 0.05 and 0.02 < calibration["std"][0] < 0.2
    assert calibration["asset"] == UNIT and calibration["start"] == start.isoformat()
    # The calibrated diagram judges the last quarter hour, 1.5 above the model, as deviating.
    end = pd.Timestamp(NOW)
    judged = run_on_asset(
        unit_diagram(calibration),
        UNIT,
        client=runtime.service_client,
        start=end - pd.Timedelta(minutes=30),
        end=end,
        step=STEP,
        models=runtime.model_runtime(),
    )
    assert judged["summary"]["verdict"]["status"] == "warning"


def test_runs_over_a_period_carry_the_blocks_memory(runtime):
    start = pd.Timestamp(NOW) - 2 * HOUR + pd.Timedelta(minutes=30)
    calibration = _calibrate(runtime, unit_diagram(), start, start + HOUR)["calibration"]
    ends = segment_ends(pd.Timestamp(NOW) - pd.Timedelta(minutes=30), pd.Timestamp(NOW), 600)
    assert ends == [pd.Timestamp(NOW) - pd.Timedelta(minutes=m) for m in (20, 10, 0)]
    runs = list(
        runs_over(
            unit_diagram(calibration),
            UNIT,
            client=runtime.service_client,
            ends=ends,
            window=1800,
            step=STEP,
            models=runtime.model_runtime(),
            keep=[("dev", "result")],
        )
    )
    statuses = [run["kept"][("dev", "result")].status for run in runs]
    # Normal, then the bias of the last fifteen minutes: attention, then a problem (persistence 2).
    assert statuses == ["ok", "warning", "bad"]
    assert runs[-1]["states"]["dev"]["streak"] == 2


def test_calibrate_says_why_it_cannot(runtime):
    start = pd.Timestamp(NOW) - HOUR
    with pytest.raises(ValueError, match="Deviation"):
        _calibrate(runtime, unit_diagram(), start, start + HOUR, node="model")
    with pytest.raises(ValueError, match="shorter than one judged part"):
        _calibrate(runtime, unit_diagram(), start, start + pd.Timedelta(minutes=5))
    unwired = unit_diagram()
    unwired["edges"] = [edge for edge in unwired["edges"] if edge["target"] != "dev"]
    with pytest.raises(ValueError, match="Wire the model's residuals"):
        _calibrate(runtime, unwired, start, start + HOUR)
    # No plant data in the period: every run is left out, and the first reason is given.
    with pytest.raises(ValueError, match="No run in the period could be used"):
        _calibrate(runtime, unit_diagram(), start - 24 * HOUR, start - 23 * HOUR)


def test_judged_part_follows_the_model_blocks():
    timing = AssetTiming.model_validate(TIMING)
    diagram = unit_diagram()
    assert judged_part(diagram, [("model", "y_residual")], timing) == 600
    diagram["nodes"][2]["parameters"] = {**diagram["nodes"][2]["parameters"], "judged_seconds": 300}
    assert judged_part(diagram, [("model", "y_residual")], timing) == 300
    assert judged_part(diagram, [("op", "value")], timing) == 1800  # no model: the window


def test_the_calibrate_endpoint_is_for_editors(tmp_path):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    start = pd.Timestamp(NOW) - 2 * HOUR + pd.Timedelta(minutes=30)
    body = {
        "diagram": unit_diagram(),
        "node_id": "dev",
        "asset_id": UNIT,
        "timing": TIMING,
        "start": start.isoformat(),
        "end": (start + HOUR).isoformat(),
    }
    try:
        with client_for(runtime, fake, "operator") as client:
            assert client.post("/link/api/algorithms/calibrate", json=body).status_code == 403
        with client_for(runtime, fake, "engineer") as client:
            answer = client.post("/link/api/algorithms/calibrate", json=body)
            assert answer.status_code == 200, answer.text
            assert answer.json()["calibration"]["outputs"] == ["y"]
            backwards = {**body, "end": body["start"]}
            assert client.post("/link/api/algorithms/calibrate", json=backwards).status_code == 422
            nowhere = {**body, "asset_id": "nowhere"}
            assert client.post("/link/api/algorithms/calibrate", json=nowhere).status_code == 404
            wrong = {**body, "node_id": "model"}
            answer = client.post("/link/api/algorithms/calibrate", json=wrong)
            assert answer.status_code == 422 and "Deviation" in answer.json()["detail"]
    finally:
        runtime.shutdown()


# A twin as an algorithm ------------------------------------------------------------------------


def test_a_twin_becomes_a_diagram_with_its_scales_band_and_judgement():
    twin = {
        "name": "Loop twin",
        "asset_id": None,
        "model_id": "plantcrafttwin-loopprocess",
        "cycle_seconds": 30,
        "horizon_seconds": 1200,
        "evaluate_seconds": 300,
        "step_seconds": 2.0,
        "parameters": {"K": 0.5, "tau": 100.0},
        "inputs": [
            {"variable": "u", "source": {"asset_id": "tic-1", "role": "op"}, "scale": 0.01},
            {"variable": "d", "source": {"signal_id": sid("FI-1.PV")}},
        ],
        "outputs": [
            {
                "variable": "y",
                "label": "TIC-1",
                "source": {"asset_id": "tic-1", "role": "pv"},
                "start_parameter": "y_start",
                "offset": -273.15,
            }
        ],
        "detection": {"confidence": 0.995, "share": 0.3, "persistence": 4, "centre": True},
        "active_when": {"source": {"signal_id": sid("FI-1.PV")}, "above": 5.0},
    }
    assert twin_subject(twin) == "tic-1"
    assert twin_timing(twin) == {"cycle_seconds": 30, "window_seconds": 1200, "step_seconds": 2}
    diagram = twin_diagram(
        twin, LOOP_INFO, {"outputs": ["y"], "mean": [0], "cov": [[1]], "samples": 9}
    )
    plan = compile_algorithm(diagram)
    assert plan.errors == [], plan.errors
    nodes = {node["id"]: node for node in diagram["nodes"]}
    # The subject's own roles need no asset; scales and offsets are Gain and offset blocks.
    assert nodes["in_1"]["parameters"] == {"role": "op"}
    assert nodes["in_1_scaled"]["parameters"] == {"gain": 0.01, "offset": 0.0}
    assert nodes["in_2"]["parameters"] == {"signal": sid("FI-1.PV")}
    assert "in_2_scaled" not in nodes
    assert nodes["out_1_scaled"]["parameters"]["offset"] == -273.15
    model = nodes["model"]["parameters"]
    assert model["p_k"] == 0.5 and model["p_tau"] == 100.0 and model["y_start"] == "y_start"
    assert model["step_seconds"] == 2.0 and model["judged_seconds"] == 300.0
    deviation = nodes["deviation"]["parameters"]
    assert deviation["persistence"] == 4 and deviation["centre"] is True
    assert deviation["calibration"]["samples"] == 9
    assert nodes["operating"]["parameters"] == {"above": 5.0, "below": None}
    assert nodes["result"]["parameters"] == {"name": "Model deviation"}
    with pytest.raises(KeyError):
        twin_diagram({**twin, "parameters": {"nowhere": 1.0}}, LOOP_INFO)


def test_unit_twin_is_shipped_on_assets_and_runs_the_builtin_model(tmp_path):
    shipped = BY_ID[UNIT_TWIN]
    assert shipped["subject_kind"] == "asset"
    assert compile_algorithm(shipped["diagram"]).errors == []
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "engineer") as client:
            found = client.get(f"/link/api/algorithms/{UNIT_TWIN}").json()
            assert found["system"] and found["subject_kind"] == "asset" and found["assets"] == []
            assert found["timing"]["cycle_seconds"] == 60
        end = pd.Timestamp(NOW)
        run = run_on_asset(
            shipped["diagram"],
            "tic-1",
            client=runtime.service_client,
            start=end - pd.Timedelta(minutes=30),
            end=end,
            step=STEP,
            models=runtime.model_runtime(),
        )
    finally:
        runtime.shutdown()
    # Not calibrated: it ran the model on the loop's own OP and PV and says so.
    blocks = run["summary"]["blocks"]
    assert run["summary"]["verdict"]["status"] == "unknown"
    assert "Not calibrated yet" in blocks["deviation"]["message"]
    assert np.isfinite(run["summary"]["recorded"][0]["points"]["v"]).all()


def test_publish_a_model_to_link_and_start_an_algorithm_around_it(tmp_path):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    fmu = next(builtin_folder().glob("*oop*.fmu")).read_bytes()
    url = "/link/api/models?name=Reactor%20loop&origin=/models/runs/3"
    try:
        with client_for(runtime, fake, "engineer") as client:
            assert client.post(url, content=fmu).status_code == 403
        with client_for(runtime, fake, "admin") as client:
            assert client.post(url, content=b"").status_code == 422
            assert client.post(url, content=b"not a zip").status_code == 422
            assert (
                client.post("/link/api/models?origin=//elsewhere", content=fmu).status_code == 422
            )
            answer = client.post(url, content=fmu)
            assert answer.status_code == 201, answer.text
            model = answer.json()
            assert model["model_id"] == "reactor-loop" and model["origin"] == "/models/runs/3"
            assert model["block_id"] == "model.fmu_reactor_loop" and not model["builtin"]
            # A block of the Models library at once, and a new algorithm around it.
            assert client.get("/link/api/blocks/model.fmu_reactor_loop").status_code == 200
            starter = client.get("/link/api/models/reactor-loop/starter").json()
            assert starter["subject_kind"] == "asset" and starter["name"] == "Reactor loop"
            assert compile_algorithm(starter["diagram"]).errors == []
            roles = {
                node["label"]: node["parameters"]["role"]
                for node in starter["diagram"]["nodes"]
                if node["block"] == "input.signal"
            }
            assert roles == {"u": "op", "d": "secondary", "y": "pv"}
            blocks = {node["block"] for node in starter["diagram"]["nodes"]}
            assert {"model.fmu_reactor_loop", "model.deviation", "output.result"} <= blocks
            renamed = client.patch(
                "/link/api/models/reactor-loop", json={"name": "Reactor", "description": "R-1"}
            )
            assert renamed.json()["name"] == "Reactor"
            builtin = client.delete("/link/api/models/plantcrafttwin-loopprocess")
            assert builtin.status_code == 409
            assert client.delete("/link/api/models/reactor-loop").status_code == 204
            assert client.get("/link/api/blocks/model.fmu_reactor_loop").status_code == 404
            runtime.settings.model_upload = False
            assert client.post(url, content=fmu).status_code == 403
    finally:
        runtime.shutdown()


def test_a_model_in_use_cannot_be_deleted(tmp_path):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    fmu = next(builtin_folder().glob("*oop*.fmu")).read_bytes()
    try:
        with client_for(runtime, fake, "admin") as client:
            client.post("/link/api/models?name=Mine", content=fmu)
            starter = client.get("/link/api/models/mine/starter").json()
            starter["diagram"]["nodes"] = [
                {**node, "parameters": {"role": "pv"}} if node["block"] == "input.signal" else node
                for node in starter["diagram"]["nodes"]
            ]
            saved = client.put(
                "/link/api/algorithms/mine",
                json={"algorithm_id": "mine", **starter, "assets": [UNIT]},
            )
            assert saved.status_code == 200, saved.text
            answer = client.delete("/link/api/models/mine")
            assert answer.status_code == 409 and "Mine" in answer.json()["detail"]
    finally:
        runtime.shutdown()
