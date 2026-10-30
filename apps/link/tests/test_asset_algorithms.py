"""Algorithms on assets: a unit's model run on its loops' signals every cycle, its verdict on the
asset, its series in the historian and its blocks' memory kept between runs."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from linkcraft.api.runtime import Runtime
from linkcraft.assets.run import run_on_asset, window_end
from linkcraft.blocks.convert import with_node_parameters
from linkcraft.blocks.models import model_block_id
from linkcraft.config import Settings
from linkcraft.engine.compute import ComputePool
from linkcraft.models.builtin import builtin_folder
from linkcraft.models.simulate import InlinePool, Simulation, run_simulation
from linkcraft.models.stats import calibrate
from tests.conftest import BASE_URL, client_for
from tests.plant import NOW, PlantFake, sid

LOOP_FMU = str(builtin_folder() / "PlantCraftTwin.LoopProcess.fmu")
MODEL = model_block_id("plantcrafttwin-loopprocess")
STEP = 5.0
TUNED = {"p_k": 0.5, "p_tau": 100.0, "p_theta": 20.0, "p_y0": 40.0, "judged_seconds": 600}
TIMING = {"cycle_seconds": 60, "window_seconds": 1800, "step_seconds": STEP}
UNIT = "furnace"


def unit_series(bias: float = 0.0, minutes: float = 15.0) -> dict[str, pd.Series]:
    """TIC-1's valve and temperature over two hours: the loop process model plus noise, the
    temperature ``bias`` above it over the last ``minutes``."""

    index = pd.date_range(NOW - timedelta(hours=2), NOW, freq=f"{STEP:g}s", tz="UTC")
    seconds = np.arange(len(index)) * STEP
    rng = np.random.default_rng(3)
    u = 50.0 + 8.0 * np.sin(seconds / 600.0) + rng.normal(0, 0.3, len(index))
    y = run_simulation(
        Simulation(
            fmu=LOOP_FMU,
            times=seconds.astype(float),
            inputs={"u": u, "d": np.full(len(index), 50.0)},
            outputs=["y"],
            start_values={"K": 0.5, "tau": 100.0, "theta": 20.0, "y0": 40.0, "y_start": 40.0},
            step=STEP,
        )
    )["y"]
    y = y + rng.normal(0, 0.05, len(index))
    y = y + np.where(seconds >= seconds[-1] - minutes * 60, bias, 0.0)
    return {sid("TIC-1.OP"): pd.Series(u, index=index), sid("TIC-1.PV"): pd.Series(y, index=index)}


def unit_fake(**changes) -> PlantFake:
    signals = [
        {"id": sid(tag), "name": tag, "source": "fake", "unit": unit, "low": 0.0, "high": 100.0}
        for tag, unit in (("TIC-1.OP", "%"), ("TIC-1.PV", "degC"))
    ]
    assets = [
        {"id": "plant", "name": "Plant", "kind": "site", "parent_id": None, "attributes": {}},
        {"id": UNIT, "name": "Furnace", "kind": "unit", "parent_id": "plant", "attributes": {}},
        {
            "id": "tic-1",
            "name": "TIC-1",
            "kind": "loop",
            "parent_id": UNIT,
            "attributes": {},
            "signals": {"op": sid("TIC-1.OP"), "pv": sid("TIC-1.PV")},
        },
    ]
    return PlantFake(assets=assets, signals=signals, series=unit_series(**changes), now=NOW)


def unit_runtime(tmp_path, fake) -> Runtime:
    settings = Settings(processcraft_url=BASE_URL, data_dir=tmp_path, scheduler_enabled=False)
    return Runtime(
        settings,
        verifier=fake.verifier("linkcraft"),
        service_client=fake.client(None, app="linkcraft", key="test-app-key"),
        http_client=fake.http_client(),
        compute=ComputePool(0),
        simulations=InlinePool(),
    )


def twin_diagram(calibration: dict | None = None) -> dict:
    """The unit's twin: TIC-1's valve (a role of another asset) into the model, its temperature
    (a signal by id) measured, the residual judged with T², the verdict on the unit."""

    return {
        "nodes": [
            {"id": "op", "block": "input.signal", "parameters": {"role": "op", "asset": "tic-1"}},
            {"id": "pv", "block": "input.signal", "parameters": {"signal": sid("TIC-1.PV")}},
            {"id": "model", "block": MODEL, "parameters": TUNED, "record": ["y", "y_residual"]},
            {
                "id": "dev",
                "block": "model.deviation",
                "parameters": {"calibration": calibration, "persistence": 2},
            },
            {"id": "out", "block": "output.result", "parameters": {"name": "Model deviation"}},
            {"id": "msg", "block": "output.message", "parameters": {}},
        ],
        "edges": [
            _wire("op", "value", "model", "u"),
            _wire("pv", "value", "model", "y_measured"),
            _wire("model", "y_residual", "dev", "residuals"),
            _wire("dev", "result", "out", "in"),
            _wire("dev", "result", "msg", "in"),
        ],
    }


def _wire(source, source_port, target, target_port):
    return {
        "source": source,
        "source_port": source_port,
        "target": target,
        "target_port": target_port,
    }


@pytest.fixture(scope="module")
def calibration(tmp_path_factory) -> dict:
    """The residuals of the healthy unit over six windows of its first ninety minutes."""

    fake = unit_fake()
    runtime = unit_runtime(tmp_path_factory.mktemp("calibration"), fake)
    rows = []
    try:
        for minutes in range(30, 90, 10):
            end = window_end(pd.Timestamp(NOW) - pd.Timedelta(minutes=minutes), STEP)
            found = run_on_asset(
                twin_diagram(),
                UNIT,
                client=runtime.service_client,
                start=end - pd.Timedelta(minutes=30),
                end=end,
                step=STEP,
                models=runtime.model_runtime(),
                keep=[("model", "y_residual")],
            )
            rows.append(found["kept"][("model", "y_residual")].dropna().to_numpy())
    finally:
        runtime.shutdown()
    return calibrate(np.concatenate(rows)[:, None], ["y"]).as_dict()


def _save(client, calibration, *, algorithm_id="unit-twin", assets=(UNIT,), diagram=None):
    answer = client.put(
        f"/link/api/algorithms/{algorithm_id}",
        json={
            "algorithm_id": algorithm_id,
            "name": "Unit twin",
            "subject_kind": "asset",
            "diagram": diagram or twin_diagram(calibration),
            "timing": TIMING,
            "assets": list(assets),
        },
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


# One run -----------------------------------------------------------------------------------


def test_a_run_reads_roles_of_other_assets_and_signals_by_id(tmp_path, calibration):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    try:
        end = pd.Timestamp(NOW)
        found = run_on_asset(
            twin_diagram(calibration),
            UNIT,
            client=runtime.service_client,
            start=end - pd.Timedelta(minutes=30),
            end=end,
            step=STEP,
            models=runtime.model_runtime(),
            algorithm_id="unit-twin",
            with_trace=True,
        )
    finally:
        runtime.shutdown()
    summary = found["summary"]
    assert summary["signals"] == {"op": sid("TIC-1.OP"), "pv": sid("TIC-1.PV")}
    assert summary["verdict"]["status"] == "ok", summary["verdict"]
    assert summary["outputs"][0]["key"] == "model_deviation"
    recorded = {entry["port"]: entry for entry in summary["recorded"]}
    assert len(recorded["y"]["points"]["t"]) == 361  # the whole window, every five seconds
    # The judged ten minutes, every five seconds, where the plant measured.
    assert 115 <= len(recorded["y_residual"]["points"]["t"]) <= 121
    assert found["trace"]["model"]["y"]["type"] == "series"
    assert found["states"]["dev"]["streak"] == 0


def test_a_missing_role_says_which_asset_and_role(tmp_path, calibration):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    diagram = twin_diagram(calibration)
    diagram["nodes"][0]["parameters"] = {"role": "op"}  # the unit itself has no OP
    try:
        end = pd.Timestamp(NOW)
        found = run_on_asset(
            diagram,
            UNIT,
            client=runtime.service_client,
            start=end - pd.Timedelta(minutes=30),
            end=end,
            step=STEP,
            models=runtime.model_runtime(),
        )
    finally:
        runtime.shutdown()
    verdict = found["summary"]["verdict"]
    assert verdict["status"] == "unknown"
    assert "Furnace has no signal for role op" in verdict["message"]


def test_an_algorithm_on_assets_runs_publishes_and_remembers(tmp_path, calibration):
    fake = unit_fake(bias=1.5, minutes=12)
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as client:
            saved = _save(client, calibration)
            assert saved["subject_kind"] == "asset"
            assert saved["assets"] == [UNIT] and saved["timing"]["cycle_seconds"] == 60
            profile = runtime.presets.get_profile("unit-twin")
            # Saving makes no schedule: a schedule chooses the algorithm and its assets.
            assert not [s for s in runtime.jobs.list_schedules() if s["profile_id"] == "unit-twin"]
            made = client.post(
                "/link/api/schedules",
                json={
                    "name": "Unit twin",
                    "profile_id": "unit-twin",
                    "selector": {"mode": "list", "ids": [UNIT, UNIT]},
                    "cadence": "interval",
                    "interval_minutes": 15,
                },
            )
            assert made.status_code == 201, made.text
            schedule = made.json()
            assert schedule["subject_kind"] == "asset" and schedule["work"] == "asset"
            assert runtime.schedule_subjects(schedule) == [UNIT]
            # An asset runs an algorithm in one schedule only.
            again = client.post(
                "/link/api/schedules",
                json={
                    "name": "Unit twin again",
                    "profile_id": "unit-twin",
                    "selector": {"mode": "list", "ids": [UNIT]},
                    "cadence": "daily",
                },
            )
            assert again.status_code == 409 and "Unit twin" in again.json()["detail"]
            assert (
                client.post(
                    "/link/api/schedules",
                    json={"name": "No assets", "profile_id": "unit-twin", "cadence": "daily"},
                ).status_code
                == 422
            )
            first = runtime.assets.run_one(profile, UNIT, now=NOW - timedelta(minutes=2))
            second = runtime.assets.run_one(profile, UNIT, now=NOW - timedelta(minutes=1))
            third = runtime.assets.run_one(profile, UNIT, now=NOW)
            # A lasting deviation: attention, then a problem once it persists for two runs.
            assert [run["status"] for run in (first, second, third)] == ["warning", "bad", "bad"]
            assert third["states"]["dev"]["streak"] == 3
            assert "TIC-1" not in third["message"] and "y explains 100%" in third["message"]
            result = fake.links.results[("linkcraft", f"asset:{UNIT}", "out_model_deviation")]
            assert result["status"] == "alarm"
            # Run without its schedule, what it records stays in Link (round 8, D6:
            # tests/test_recorded_outputs.py has what a schedule writes).
            assert not [key for key in fake.series_data if key.startswith(f"app-linkcraft:{UNIT}.")]
            alerts = [
                event for event in fake.links.events if event["kind"] == "linkcraft.protocol.alert"
            ]
            assert len(alerts) == 1 and alerts[0]["subject"] == f"asset:{UNIT}"
            runs = client.get("/link/api/algorithms/unit-twin/runs").json()
            assert [(row["asset_id"], row["status"]) for row in runs] == [(UNIT, "bad")]
            link = client.get(f"/link/api/assets/{UNIT}").json()
            assert link["covered"] is True and link["runs"][0]["algorithm_id"] == "unit-twin"
            # Its result is a row of Results like any other.
            found = client.get("/link/api/results?kind=asset").json()
            (row,) = found["items"]
            assert row["status"] == "alarm" and row["algorithm"]["id"] == "unit-twin"
            assert row["path"] == f"/assets/{UNIT}" and row["name"]
            # Saving a changed diagram starts its blocks' memory afresh; dropping the asset
            # drops its run.
            _save(client, {**calibration, "samples": calibration["samples"] + 1})
            assert runtime.asset_runs.get("unit-twin", UNIT)["states"] == {}
            _save(client, calibration, assets=())
            assert runtime.asset_runs.list("unit-twin") == []
    finally:
        runtime.shutdown()


def test_the_schedules_link_once_made_for_an_algorithm_become_ordinary(tmp_path, calibration):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as client:
            _save(client, calibration)
        # What an older Link left: a "cycle" schedule every minute over the algorithm's assets,
        # and one for an algorithm that no longer exists.
        for profile_id in ("unit-twin", "gone"):
            runtime.jobs.create_schedule(
                schedule_id=f"algorithm-{profile_id}",
                name=profile_id,
                loop_id="*",
                cadence="interval",
                interval_minutes=1,
                timezone="UTC",
                lookback_minutes=0,
                profile_id=profile_id,
                method_config={},
                subject_kind="asset",
                selector={"mode": "algorithm"},
                kind="cycle",
            )
        assert runtime.migrate_asset_schedules() == 2
        assert runtime.migrate_asset_schedules() == 0
        assert runtime.jobs.get_schedule("algorithm-gone") is None
        moved = runtime.jobs.get_schedule("algorithm-unit-twin")
        assert moved["kind"] == "protocol" and moved["interval_minutes"] == 15
        assert moved["selector"] == {"mode": "list", "ids": [UNIT]}
        assert runtime.schedule_subjects(moved) == [UNIT]
    finally:
        runtime.shutdown()


def test_the_editor_tests_on_an_asset_at_a_chosen_time(tmp_path, calibration):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "engineer") as client:
            answer = client.post(
                "/link/api/algorithms/test",
                json={
                    "diagram": twin_diagram(calibration),
                    "asset_id": UNIT,
                    "timing": TIMING,
                    "end": NOW.isoformat(),
                },
            )
            assert answer.status_code == 200, answer.text
            body = answer.json()
            assert body["asset_name"] == "Furnace"
            assert body["summary"]["verdict"]["status"] == "ok"
            assert body["trace"]["dev"]["result"]["status"] == "ok"
            missing = client.post(
                "/link/api/algorithms/test",
                json={"diagram": twin_diagram(calibration), "asset_id": "nowhere"},
            )
            assert missing.status_code == 404
    finally:
        runtime.shutdown()


def test_models_run_only_on_assets_and_are_listed(tmp_path, calibration):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as client:
            answer = client.put(
                "/link/api/algorithms/loop-twin",
                json={
                    "algorithm_id": "loop-twin",
                    "name": "Loop twin",
                    "subject_kind": "loop",
                    "diagram": twin_diagram(calibration),
                },
            )
            assert answer.status_code == 422
            assert "Model blocks run in algorithms on assets" in answer.text
            _save(client, calibration)
            models = {item["model_id"]: item for item in client.get("/link/api/models").json()}
            loop = models["plantcrafttwin-loopprocess"]
            assert loop["builtin"] and loop["block_id"] == MODEL
            assert [item["name"] for item in loop["outputs"]] == ["y"]
            # The shipped Unit twin runs this model too.
            used = {item["algorithm_id"] for item in loop["used_by"]}
            assert used == {"unit-twin", "unit_twin"}
            assert client.get("/link/api/models/nowhere").status_code == 404
            run = client.post("/link/api/algorithms/unit-twin/run")
            assert run.status_code == 200 and run.json()[0]["asset_id"] == UNIT
    finally:
        runtime.shutdown()


def test_the_assets_an_algorithm_may_name_come_with_their_path(tmp_path):
    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "engineer") as client:
            choices = {item["id"]: item for item in client.get("/link/api/asset-choices").json()}
    finally:
        runtime.shutdown()
    assert choices["tic-1"] == {
        "id": "tic-1",
        "name": "TIC-1",
        "kind": "loop",
        "path": "Plant / Furnace",
        "roles": ["op", "pv"],
    }


def test_a_monitor_sets_its_own_parameter_values_on_top_of_the_algorithm(tmp_path, calibration):
    """Defaults cascade: the block's default, then the algorithm's value,
    then the monitor's own; the monitor keeps only what its algorithm's blocks have."""

    fake = unit_fake()
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as client:
            _save(client, calibration)
            base = {
                "name": "Unit twin",
                "profile_id": "unit-twin",
                "selector": {"mode": "list", "ids": [UNIT]},
                "cadence": "daily",
            }
            wrong = client.post(
                "/link/api/schedules", json={**base, "node_parameters": {"nope": {"x": 1}}}
            )
            assert wrong.status_code == 422
            unknown = client.post(
                "/link/api/schedules", json={**base, "node_parameters": {"out": {"nope": 1}}}
            )
            assert unknown.status_code == 422
            made = client.post(
                "/link/api/schedules",
                json={**base, "node_parameters": {"out": {"name": "Furnace drift"}}},
            )
            assert made.status_code == 201, made.text
            schedule = made.json()
            assert schedule["method_config"]["node_parameters"] == {
                "out": {"name": "Furnace drift"}
            }
            # None follows the algorithm again.
            patched = client.patch(
                f"/link/api/schedules/{schedule['schedule_id']}",
                json={"node_parameters": {"out": {"name": None}}},
            )
            assert patched.status_code == 200, patched.text
            assert "node_parameters" not in patched.json()["method_config"]
        profile = runtime.presets.get_profile("unit-twin")
        config = with_node_parameters(profile["method_config"], {"out": {"name": "Drift"}})
        nodes = {node["id"]: node for node in config["diagram"]["nodes"]}
        assert nodes["out"]["parameters"]["name"] == "Drift"
        assert nodes["dev"]["parameters"] == next(
            node["parameters"]
            for node in profile["method_config"]["diagram"]["nodes"]
            if node["id"] == "dev"
        )
    finally:
        runtime.shutdown()
