"""Link's objects for notebooks: the routes PlantCraft forwards (``plantcraft-objects/1``), the
examples and the runtime, and blocks and algorithms run the way a notebook runs them
(``linkcraft.notebook``) on the known-fault plant."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from plantcraft_sdk import apptest
from plantcraft_sdk.client import NotFound
from plantcraft_sdk.notebooks import example_problems

from linkcraft import notebook
from linkcraft.notebook_examples import EXAMPLES
from tests.plant import NOW, sid

ROOT = Path(__file__).resolve().parents[1]
START, END = (NOW - timedelta(hours=4)).isoformat(), NOW.isoformat()


class PlantError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Plant:
    """What ``plantcraft_notebook`` gives the runtime (asset, series, moment), on the fake."""

    PlantCraftError = PlantError

    def __init__(self, client):
        self.client = client

    def asset(self, asset_id):
        try:
            return self.client.asset(asset_id)
        except NotFound as exc:
            raise PlantError(404, str(exc)) from exc

    def series(self, ids, start, end, step=None):
        columns, _ = self.client.series_many_pandas(ids, start, end, step)
        return pd.DataFrame(columns)

    @staticmethod
    def moment(value):
        return NOW if value == "now" else pd.Timestamp(value).to_pydatetime()


class App:
    """``pc.app("link")`` as the runtime uses it: one object by kind and id, through the routes."""

    def __init__(self, client):
        self.client = client

    def get(self, kind, object_id):
        answer = self.client.get(f"/link/api/objects/{kind}/{object_id}")
        assert answer.status_code == 200, answer.text
        return answer.json()


@pytest.fixture
def plant(fake):
    return Plant(fake.client("engineer"))


def test_link_serves_its_objects_examples_and_runtime_in_the_suite_format(client):
    assert apptest.objects_problems(client, "/link", ROOT) == []
    blocks = client.get("/link/api/objects/block").json()["items"]
    spikes = next(item for item in blocks if item["id"] == "dq.spikes")
    assert spikes["library"] == "dq" and spikes["runs_here"] is True and spikes["inputs"] == "x"
    one = client.get("/link/api/objects/block/dq.spikes").json()
    assert one["kind"] == "block" and [port["port"] for port in one["inputs"]] == ["x"]
    algorithms = client.get("/link/api/objects/algorithm").json()["items"]
    first = client.get(f"/link/api/objects/algorithm/{algorithms[0]['id']}").json()
    assert first["diagram"]["nodes"] and "timing" in first
    runtime = client.get("/link/api/notebooks/runtime")
    names = zipfile.ZipFile(io.BytesIO(runtime.content)).namelist()
    assert "linkcraft/notebook.py" in names and "plantcraft_sdk/blocks/graph.py" in names
    manifest = json.loads(
        zipfile.ZipFile(io.BytesIO(runtime.content)).read("plantcraft-runtime.json")
    )
    assert manifest["entry"] == "linkcraft.notebook" and manifest["app"] == "linkcraft"
    assert not any(name.endswith(".pyc") for name in names)


def test_the_examples_are_written_right():
    assert example_problems(EXAMPLES) == []
    assert [item.id for item in EXAMPLES] == [
        "run-a-block",
        "write-a-block",
        "run-an-algorithm",
        "loop-health",
    ]


def test_a_block_runs_on_an_assets_signals_by_role(plant, client):
    item = App(client).get("block", "dq.spikes")
    run = notebook.run("block", item, plant, App(client), asset="fic-101", start=START, end=END)
    verdict = run.values()["result"]
    # A quality check reads the samples as recorded, so it judges them.
    assert verdict["status"] in {"ok", "warning", "bad"}, verdict


def test_a_block_runs_on_series_of_ones_own_and_on_signal_ids(plant, client):
    data = plant.series([sid("FIC-101.PV")], START, END, step=60)[sid("FIC-101.PV")]
    item = App(client).get("block", "transform.moving_average")
    smooth = notebook.run("block", item, plant, App(client), x=data, window_samples=10)
    table = smooth.table()
    assert list(table.columns) == ["value"] and len(table) == len(data)
    assert abs(table["value"].iloc[-1] - data.iloc[-10:].mean()) < 1e-6
    errors = App(client).get("block", "cpm.error_metrics_basic")
    found = notebook.run(
        "block",
        errors,
        plant,
        App(client),
        pv=sid("FIC-101.PV"),
        sp=sid("FIC-101.SP"),
        start=START,
        end=END,
        step=10,
    )
    assert found.values()["mae"] >= 0


def test_a_block_says_what_it_needs(plant, client):
    item = App(client).get("block", "dq.spikes")
    with pytest.raises(TypeError, match="no input or parameter colour"):
        notebook.run("block", item, plant, App(client), asset="fic-101", colour="red")
    with pytest.raises(ValueError, match="Say where x comes from"):
        notebook.run("block", item, plant, App(client))


def test_an_algorithm_runs_whole_on_an_asset(plant, client):
    items = client.get("/link/api/objects/algorithm").json()["items"]
    chosen = next(item["id"] for item in items if "flow" in item["name"].lower())
    algorithm = App(client).get("algorithm", chosen)
    run = notebook.run(
        "algorithm", algorithm, plant, App(client), asset="fic-101", start=START, end=END
    )
    assert run.verdict["status"]
    assert run.outputs and run.summary["algorithm"] == chosen


def test_a_block_file_is_tested_as_link_tests_it(plant, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "plantcraft_notebook", plant)
    block = {
        "format": "plantcraft-block/1",
        "name": "Time above a limit",
        "library": "custom",
        "docs": {"summary": "Share of the window above a limit."},
        "inputs": [{"port": "x", "type": "series", "label": "Signal"}],
        "outputs": [{"port": "share", "type": "number", "label": "Share above", "unit": "%"}],
        "parameters": [{"name": "limit", "type": "number", "title": "Limit", "default": 0}],
        "code": (
            "def run(inputs, params, ctx):\n"
            "    x = inputs['x'].dropna()\n"
            "    return {'share': float((x > params.limit).mean() * 100)}\n"
        ),
    }
    data = pd.Series(
        [1.0, 2.0, 3.0, 4.0], index=pd.date_range(NOW, periods=4, freq="min", tz="UTC"), name="x"
    )
    assert notebook.test_block(block, x=data, limit=2.5).values()["share"] == 50.0
    bad = {**block, "code": "import os\ndef run(inputs, params, ctx):\n    return {}\n"}
    with pytest.raises(ValueError):
        notebook.test_block(bad, x=data)


def test_a_model_block_says_it_runs_only_in_link(client):
    with pytest.raises(LookupError):
        notebook._site_block("model.fmu_missing", App(client), {"file": {}})


def test_the_window_widens_its_step_for_long_periods():
    begin, finish, step = notebook._window(
        notebook.AssetTiming(),
        "2026-09-01T00:00:00+00:00",
        "2026-10-01T00:00:00+00:00",
        None,
        SimpleNamespace(moment=lambda value: pd.Timestamp(value).to_pydatetime()),
    )
    assert (finish - begin).total_seconds() / step <= notebook.MAX_POINTS


# What a person's computer and the browser have (Pyodide, the kit): no web server, no HTTP client.
SERVER_ONLY = ("httpx", "jwt", "cryptography", "fastapi", "starlette", "uvicorn", "fmpy", "lxml")


def test_the_runtime_imports_with_only_what_a_notebook_has(client, tmp_path):
    runtime = client.get("/link/api/notebooks/runtime").content
    zipfile.ZipFile(io.BytesIO(runtime)).extractall(tmp_path / "runtime")
    script = f"""
import importlib.abc, sys
class Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in {SERVER_ONLY!r}:
            raise ImportError(f"{{name}} is not in a notebook")
sys.meta_path.insert(0, Refuse())
sys.path.insert(0, {str(tmp_path / "runtime")!r})
import linkcraft.notebook
assert linkcraft.notebook.__file__.startswith({str(tmp_path)!r})
"""
    done = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr[-2000:]


def test_every_example_runs_as_a_notebook_runs_it(client, fake):
    problems = apptest.run_examples(EXAMPLES, client, "/link", fake, root=ROOT)
    assert problems == [], "\n".join(problems)
