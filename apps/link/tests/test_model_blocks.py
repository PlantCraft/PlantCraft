"""The Models library: published FMUs become blocks, and the deviation block judges the plant
against them (what PlantCraft Twin did, now inside Link's algorithms)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.blocks import Context, NoData, check_catalog, execute

from linkcraft.blocks import CATALOG, compile_algorithm, register_models
from linkcraft.blocks.models import (
    DEVIATION,
    OPERATING,
    ModelRuntime,
    layout_of,
    model_block,
    model_block_id,
)
from linkcraft.db import Database
from linkcraft.models.builtin import builtin_folder, register_builtins
from linkcraft.models.fmu import FmuError, inspect_fmu
from linkcraft.models.simulate import InlinePool, Simulation, run_simulation
from linkcraft.models.stats import calibrate
from linkcraft.models.store import ModelStore

FMUS = builtin_folder()
LOOP = FMUS / "PlantCraftTwin.LoopProcess.fmu"
LOOP_ID = "plantcrafttwin-loopprocess"
STEP = 5.0
START = pd.Timestamp("2026-10-22T08:00:00Z")
TUNED = {"p_k": 0.5, "p_tau": 100.0, "p_theta": 20.0, "p_y0": 40.0}


def rezip(source: Path, keep=lambda name: True, extra: dict[str, bytes] | None = None) -> bytes:
    """``source`` with only the members ``keep`` accepts, plus ``extra``."""

    out = io.BytesIO()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(out, "w") as new:
        for item in old.infolist():
            if keep(item.filename):
                new.writestr(item, old.read(item))
        for name, data in (extra or {}).items():
            new.writestr(name, data)
    return out.getvalue()


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    folder = tmp_path_factory.mktemp("models")
    models = ModelStore(Database(folder / "link.db"), folder / "files")
    assert register_builtins(models) == 2
    return models


@pytest.fixture(scope="module")
def runtime(store):
    return ModelRuntime(store, InlinePool())


def plant(minutes: float = 30, *, bias: float = 0.0, seed: int = 1) -> dict[str, pd.Series]:
    """The loop process as the plant measures it: the model itself plus noise (and a bias)."""

    times = np.arange(0.0, minutes * 60 + STEP, STEP)
    u = np.where(times >= 300.0, 60.0, 50.0)
    d = np.full(len(times), 50.0)
    y = run_simulation(
        Simulation(
            fmu=str(LOOP),
            times=times,
            inputs={"u": u, "d": d},
            outputs=["y"],
            start_values={"K": 0.5, "tau": 100.0, "theta": 20.0, "y0": 40.0, "y_start": 40.0},
            step=STEP,
        )
    )["y"]
    rng = np.random.default_rng(seed)
    index = START + pd.to_timedelta(times, unit="s")
    measured = y + rng.normal(0.0, 0.05, len(times)) + bias
    return {
        "u": pd.Series(u, index=index),
        "d": pd.Series(d, index=index),
        "y_measured": pd.Series(measured, index=index),
    }


def run_model(runtime, inputs, **parameters):
    block = model_block(runtime.store.get(LOOP_ID))
    values = {**TUNED, **parameters}
    index = inputs["y_measured"].index
    context = Context(start=index[0], end=index[-1], extra={"models": runtime}, node_id="model")
    return block.run(inputs, block.spec.parameters.model_validate(values), context)


# The library -------------------------------------------------------------------------------


def test_inspect_reads_the_variables_and_platforms():
    info = inspect_fmu(LOOP)
    assert info.fmi_version.startswith("2.")
    assert info.runs_here is True
    by_name = {item["name"]: item for item in info.variables}
    assert by_name["u"]["causality"] == "input"
    assert by_name["y"]["causality"] == "output"
    assert by_name["y_start"]["causality"] == "parameter"
    assert by_name["tau"]["start"] == 150


@pytest.mark.parametrize(
    "data, words",
    [
        (b"not a zip", "not an FMU"),
        (rezip(LOOP, keep=lambda name: name != "modelDescription.xml"), "modelDescription.xml"),
        (rezip(LOOP, extra={"../evil.sh": b"echo"}), "outside"),
    ],
)
def test_bad_files_are_refused(tmp_path, data, words):
    path = tmp_path / "bad.fmu"
    path.write_bytes(data)
    with pytest.raises(FmuError) as raised:
        inspect_fmu(path)
    assert words in str(raised.value)


def test_models_run_from_a_folder_unpacked_once_under_the_data_folder(store):
    """The suite mounts /tmp noexec: an FMU's library must load from the data folder."""

    model = store.get(LOOP_ID)
    folder = store.runnable(model)
    assert folder.is_relative_to(store.folder)
    assert (folder / "modelDescription.xml").is_file()
    stamp = (folder / "modelDescription.xml").stat().st_mtime_ns
    assert (store.runnable(model) / "modelDescription.xml").stat().st_mtime_ns == stamp


# A published model is a block --------------------------------------------------------------


def test_a_published_model_becomes_a_documented_block_and_leaves_when_removed(store):
    try:
        listed = register_models(store.list())
        assert model_block_id(LOOP_ID) in listed and len(listed) == 2
        assert check_catalog(CATALOG) == []
        spec = CATALOG[model_block_id(LOOP_ID)].spec
        assert [port.port_id for port in spec.inputs] == ["d", "u", "y_measured"]
        assert [port.port_id for port in spec.outputs] == ["y", "y_residual"]
        fields = spec.parameters.model_fields
        assert fields["y_start"].default == "y_start"  # the output starts from the plant
        assert {"p_k", "p_tau", "p_theta", "step_seconds", "judged_seconds"} <= set(fields)
        register_models([])
        assert not [key for key in CATALOG if key.startswith("model.fmu_")]
    finally:
        register_models([])


def test_ports_never_clash_whatever_the_fmu_calls_its_variables():
    variables = [
        {"name": "T", "causality": "input", "numeric": True},
        {"name": "t", "causality": "output", "numeric": True},
        {"name": "T measured", "causality": "input", "numeric": True},
        {"name": "1x", "causality": "parameter", "numeric": True},
        {"name": "label", "causality": "parameter", "numeric": False},
    ]
    layout = layout_of({"variables": variables})
    ports = [port for port, _ in layout.inputs] + [port for port, _ in layout.outputs]
    ports += [f"{port}_measured" for port, _ in layout.outputs]
    ports += [f"{port}_residual" for port, _ in layout.outputs]
    assert len(ports) == len(set(ports))
    assert [field for field, _ in layout.parameters] == ["p_v_1x"]


def test_the_model_follows_a_healthy_plant(runtime):
    given = run_model(runtime, plant(), judged_seconds=600)
    predicted, residual = given["y"], given["y_residual"]
    assert predicted.iloc[-1] == pytest.approx(45.0, abs=0.05)
    judged = residual.dropna()
    assert len(judged) == 121  # the last ten minutes, every five seconds
    assert abs(judged.mean()) < 0.03 and judged.std() < 0.08


def test_the_run_starts_where_the_plant_was(runtime):
    """y starts from the measurement, not from the model's own y_start."""

    data = plant(bias=2.0)
    given = run_model(runtime, data, judged_seconds=600)
    assert given["y"].iloc[0] == pytest.approx(data["y_measured"].iloc[:3].mean(), abs=1e-6)


def test_missing_inputs_say_why_on_every_output(runtime):
    data = plant()
    data["u"] = data["u"].iloc[:100]
    given = run_model(runtime, data)
    assert all(isinstance(value, NoData) for value in given.values())
    assert "no values for" in given["y"].reason


def test_an_unpublished_model_says_so(runtime):
    block = model_block(runtime.store.get(LOOP_ID))
    context = Context(extra={"models": ModelRuntime(_Empty(), InlinePool())}, node_id="m")
    given = block.run(plant(), block.spec.parameters(), context)
    assert "not published" in given["y_residual"].reason


class _Empty:
    def get(self, _model_id):
        return None


# Deviation (T²) ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def calibration(runtime) -> dict:
    """The residuals of three healthy runs: what Calibrate keeps in the deviation block."""

    rows = []
    for seed in range(1, 4):
        residual = run_model(runtime, plant(seed=seed), judged_seconds=1200)["y_residual"]
        rows.append(residual.dropna().to_numpy())
    return calibrate(np.concatenate(rows)[:, None], ["y"]).as_dict()


def judge_runs(runtime, calibration, biases, **parameters):
    states: dict = {}
    found = []
    for number, bias in enumerate(biases):
        residual = run_model(runtime, plant(bias=bias, seed=10 + number))["y_residual"]
        context = Context(states=states, node_id="dev")
        values = {"calibration": calibration, **parameters}
        found.append(
            DEVIATION.run({"residuals": [residual]}, DEVIATION.spec.parameters(**values), context)
        )
    return found


def test_a_healthy_plant_is_normal_and_a_lasting_bias_becomes_a_problem(runtime, calibration):
    healthy = judge_runs(runtime, calibration, [0.0, 0.0])
    assert [item["result"].status for item in healthy] == ["ok", "ok"]
    assert healthy[0]["exceed"] < 10
    shifted = judge_runs(runtime, calibration, [1.0, 1.0, 1.0, 0.0], persistence=3)
    assert [item["result"].status for item in shifted] == ["warning", "warning", "bad", "ok"]
    problem = shifted[2]["result"]
    assert "y explains 100%" in problem.message and "above the model" in problem.message
    assert problem.detail["streak"] == 3


def test_the_deviation_block_says_why_it_cannot_judge(runtime, calibration):
    residual = run_model(runtime, plant())["y_residual"]
    context = Context(node_id="dev")
    parameters = DEVIATION.spec.parameters()
    found = DEVIATION.run({"residuals": [residual]}, parameters, context)
    assert found["result"].status == "unknown"
    assert "Not calibrated" in found["result"].message
    gone = DEVIATION.run({"residuals": [NoData("Model failed.")]}, parameters, context)
    assert gone["result"].message == "Model failed."
    stopped = pd.Series(False, index=residual.index)
    calibrated = DEVIATION.spec.parameters(calibration=calibration)
    idle = DEVIATION.run({"residuals": [residual], "active": stopped}, calibrated, context)
    assert "out of operation" in idle["result"].message
    with pytest.raises(ValueError):
        DEVIATION.spec.parameters(calibration={"outputs": "nonsense"})


def test_the_operating_band_marks_when_the_unit_runs():
    level = pd.Series([0.0, 5.0, 50.0, 80.0], index=pd.date_range(START, periods=4, freq="5s"))
    parameters = OPERATING.spec.parameters(above=10.0, below=60.0)
    inside = OPERATING.run({"x": level}, parameters, Context())["intervals"]
    assert inside.tolist() == [False, False, True, False]
    with pytest.raises(ValueError):
        OPERATING.spec.parameters()


def test_a_twin_diagram_checks_and_runs(store, runtime, calibration):
    try:
        register_models(store.list())
        model = model_block_id(LOOP_ID)
        diagram = {
            "nodes": [
                {"id": "model", "block": model, "parameters": TUNED},
                {
                    "id": "dev",
                    "block": "model.deviation",
                    "parameters": {"calibration": calibration},
                },
                {"id": "out", "block": "output.result", "parameters": {"name": "Model deviation"}},
            ],
            "edges": [
                {
                    "source": "model",
                    "source_port": "y_residual",
                    "target": "dev",
                    "target_port": "residuals",
                },
                {"source": "dev", "source_port": "result", "target": "out", "target_port": "in"},
            ],
        }
        plan = compile_algorithm(diagram)
        assert plan.errors == []
        data = plant()
        index = data["u"].index
        context = Context(start=index[0], end=index[-1], extra={"models": runtime})
        # Inputs reach the model through blocks in a real run; here they are fed directly.
        original = CATALOG[model].run
        CATALOG[model] = CATALOG[model].__class__(
            CATALOG[model].spec, lambda _inputs, p, ctx: original({**_inputs, **data}, p, ctx)
        )
        values = execute(plan, CATALOG, context)
        assert values.get("dev", "result").status == "ok", values.get("dev", "result").message
        assert context.extra["collected"]["outputs"][0]["key"] == "model_deviation"
    finally:
        register_models([])
