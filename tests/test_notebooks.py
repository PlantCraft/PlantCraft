"""Notebooks: the switch, the notebooks PlantCraft writes for each person, JupyterLite served to
them only, and the ``plantcraft-notebook`` package reading API v1 (docs/en/notebooks.md)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plantcraft.notebooks import NotebookStore, file_name, templates
from tests.test_route_permissions import ADMIN_PASSWORD, _login, app  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "notebooks" / "python"))
import plantcraft_notebook as pc  # noqa: E402


@pytest.fixture()
def dist(tmp_path, monkeypatch):
    """A stand-in for JupyterLite's build: a page and the package's wheel."""

    root = tmp_path / "lite"
    (root / "lab").mkdir(parents=True)
    (root / "lab" / "index.html").write_text("<html>lab</html>")
    (root / "pypi").mkdir()
    (root / "pypi" / "plantcraft_notebook-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    (root / "jupyter-lite.json").write_text('{"jupyter-config-data": {}}')
    (root / "static" / "pyodide").mkdir(parents=True)
    (root / "static" / "pyodide" / "pyodide.asm.wasm").write_bytes(b"\0asm" * 10)
    (tmp_path / "secret.txt").write_text("outside")
    monkeypatch.setenv("PLANTCRAFT_NOTEBOOKS_DIST", str(root))
    return root


def _turn_on(app):  # noqa: F811
    admin = _login(app, "admin", ADMIN_PASSWORD)
    assert admin.put("/api/notebooks/settings", json={"enabled": True}).status_code == 200
    return admin


def _signal(client: TestClient) -> str:
    return client.get("/api/v1/signals").json()[0]["id"]


def test_notebooks_are_off_until_an_administrator_turns_them_on(app, dist):  # noqa: F811
    with TestClient(app):
        vera = _login(app, "vera", "vera-strong-password")
        overview = vera.get("/api/notebooks").json()
        assert overview["enabled"] is False and overview["built"] is True
        assert vera.post("/api/notebooks", json={"kind": "blank"}).status_code == 409
        assert vera.get("/notebooks/lite/lab/index.html").status_code == 404
        assert vera.put("/api/notebooks/settings", json={"enabled": True}).status_code == 403
        assert vera.get("/api/v1/me").json()["notebooks_url"] is None
        admin = _turn_on(app)
        assert vera.get("/api/notebooks").json()["enabled"] is True
        # The apps' pages show "Open in a notebook" from API v1 (the Historian's Export page).
        assert vera.get("/api/v1/me").json()["notebooks_url"] == "/notebooks"
        rows = admin.get("/api/audit", params={"action": "notebooks"}).json()["rows"]
    assert rows[0]["action"] == "notebooks.settings"
    assert rows[0]["detail"] == {"enabled": True, "kit_enabled": True}


def test_the_switch_stays_off_when_the_installation_says_so(app, dist, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PLANTCRAFT_NOTEBOOKS", "off")
    with TestClient(app):
        admin = _login(app, "admin", ADMIN_PASSWORD)
        assert admin.put("/api/notebooks/settings", json={"enabled": True}).status_code == 409


def test_a_notebook_of_signals_is_in_its_owners_folder_only(app, dist):  # noqa: F811
    with TestClient(app):
        _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        signal = _signal(vera)
        created = vera.post(
            "/api/notebooks",
            json={"kind": "series", "signals": [signal], "start": "2026-01-01T00:00:00Z",
                  "end": "2026-01-02T00:00:00Z", "origin": "the Historian export"},
        )  # fmt: skip
        assert created.status_code == 201, created.text
        item = created.json()
        assert item["path"].startswith("My notebooks/") and item["path"].endswith(".ipynb")
        # JupyterLite under its build's own path (plantcraft/notebooks/dist.py).
        build = vera.get("/api/notebooks").json()["browser"]["build"]
        base = f"/notebooks/lite/v/{build}/"
        assert item["url"].startswith(f"{base}lab/index.html?path=My%20notebooks/")

        root = vera.get(f"{base}api/contents/all.json").json()
        assert [entry["name"] for entry in root["content"]] == ["Examples", "My notebooks"]
        folder = vera.get(f"{base}api/contents/My notebooks/all.json").json()
        assert [entry["path"] for entry in folder["content"]] == [item["path"]]
        assert folder["content"][0]["type"] == "notebook"
        # The examples are a folder too, read from here: a person's edits are kept by the browser.
        # One folder per app: PlantCraft's own, then each app's.
        folders = vera.get(f"{base}api/contents/Examples/all.json").json()["content"]
        assert [entry["name"] for entry in folders] == ["PlantCraft"]
        assert folders[0]["type"] == "directory"
        examples = vera.get(f"{base}api/contents/Examples/PlantCraft/all.json").json()["content"]
        assert [entry["name"] for entry in examples] == [
            f"{example['title']}.ipynb" for example in templates.examples()
        ]
        assert examples[0]["path"].startswith("Examples/PlantCraft/")
        example = vera.get(f"{base}files/{examples[0]['path']}").json()
        assert example["nbformat"] == 4
        assert vera.get(f"{base}files/Examples/none.ipynb").status_code == 404
        # A notebook opened from the folder of the first builds still opens.
        assert vera.get(f"{base}files/PlantCraft/{item['name']}").json()["nbformat"] == 4

        notebook = vera.get(f"/notebooks/lite/files/{item['path']}").json()
        assert notebook["nbformat"] == 4 and notebook["metadata"]["kernelspec"]["name"] == "python"
        code = "\n".join(cell["source"] for cell in notebook["cells"])
        assert signal in code and "%pip install -q plantcraft-notebook" in code
        assert "the Historian export" in notebook["cells"][0]["source"]

        page = vera.get(f"{base}lab/index.html")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
        # The build's files are kept by the browser for a year; another build's are not.
        kept = vera.get(f"{base}static/pyodide/pyodide.asm.wasm")
        assert "immutable" in kept.headers["cache-control"]
        old = vera.get("/notebooks/lite/v/000000000000/static/pyodide/pyodide.asm.wasm")
        assert old.status_code == 200 and "cache-control" not in old.headers
        assert (
            "cache-control"
            not in vera.get("/notebooks/lite/static/pyodide/pyodide.asm.wasm").headers
        )
        files = vera.get("/api/notebooks/files").json()
        assert (
            files["build"] == build and f"{base}static/pyodide/pyodide.asm.wasm" in files["files"]
        )
        assert not any(path.endswith((".html", ".json")) for path in files["files"])
        assert vera.get("/notebooks/lite/pypi/plantcraft_notebook-0.1.0-py3-none-any.whl").content
        for path in ("/notebooks/lite/%2e%2e/secret.txt", "/notebooks/lite/..%2fsecret.txt"):
            assert vera.get(path).status_code == 404

        eddie = _login(app, "eddie", "eddie-strong-password")
        assert eddie.get(f"{base}api/contents/My notebooks/all.json").json()["content"] == []
        assert eddie.get(f"/notebooks/lite/files/{item['path']}").status_code == 404
        assert TestClient(app).get("/notebooks/lite/lab/index.html").status_code == 401

        mine = vera.get("/api/notebooks").json()
        assert [entry["name"] for entry in mine["notebooks"]] == [item["name"]]
        assert mine["package"]["url"].endswith("plantcraft_notebook-0.1.0-py3-none-any.whl")
        assert eddie.delete(f"/api/notebooks/{item['notebook_id']}").status_code == 404
        assert vera.delete(f"/api/notebooks/{item['notebook_id']}").status_code == 200
        assert vera.get("/api/notebooks").json()["notebooks"] == []


def test_a_notebook_needs_what_it_loads(app, dist):  # noqa: F811
    with TestClient(app):
        _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        assert vera.post("/api/notebooks", json={"kind": "series"}).status_code == 422
        assert vera.post("/api/notebooks", json={"kind": "asset"}).status_code == 422
        asset = vera.post("/api/notebooks", json={"kind": "asset", "asset_id": "FIC-101"}).json()
        assert asset["name"] == "FIC-101.ipynb"


def _routed(client: TestClient):
    """``plantcraft_notebook`` on a computer, its requests answered by the test app."""

    def send(self, method, path, body, accept="application/json"):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": accept,
        }
        answer = client.request(method, path, content=body, headers=headers)
        retry = answer.headers.get("retry-after", "")
        return answer.status_code, answer.content, retry, answer.headers.get("content-type", "")

    return send


def test_the_package_reads_the_plant_with_a_persons_access_token(app, dist, monkeypatch):  # noqa: F811
    with TestClient(app):
        admin = _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        token = vera.post("/api/assistant-access/mine", json={"label": "laptop"}).json()["token"]
        signal = _signal(vera)
        reader = TestClient(app)
        monkeypatch.setattr(pc.Client, "_fetch", _routed(reader))
        pc.connect("http://testserver", token=token)
        assert pc.me()["username"] == "vera"
        assert signal in pc.signals().index
        data = pc.series([signal], "2000-01-01", "now", step=3600)
        assert isinstance(data.index, pd.DatetimeIndex) and str(data.index.tz) == "UTC"
        assert list(data.columns) == [signal]

        # Reads only: an access token writes nothing.
        event = {"kind": "note", "subject": "asset:FIC-101", "summary": "x"}
        answer = reader.post(
            "/api/v1/events", json=event, headers={"Authorization": f"Bearer {token}"}
        )
        assert answer.status_code == 403
        admin.put("/api/notebooks/settings", json={"enabled": False})
        with pytest.raises(pc.PlantCraftError) as refused:
            pc.me()
        assert refused.value.status == 401


def test_relative_and_naive_times_are_utc():
    now = pd.Timestamp("2026-10-23T12:00:00Z").to_pydatetime()
    assert pc.iso(pc.moment("-1d", now=now)) == "2026-10-22T12:00:00.000Z"
    assert pc.iso(pc.moment("now", now=now)) == "2026-10-23T12:00:00.000Z"
    assert pc.iso(pc.moment("2026-10-01 08:00")) == "2026-10-01T08:00:00.000Z"
    assert pc.iso(pc.moment("2026-10-01T08:00:00-03:00")) == "2026-10-01T11:00:00.000Z"


def test_names_are_safe_and_a_person_keeps_the_newest(tmp_path, monkeypatch):
    from plantcraft.db import Database

    assert file_name("FIC-101/PV: last week?") == "FIC-101 PV last week.ipynb"
    assert file_name("../..") == "Notebook.ipynb"
    monkeypatch.setattr("plantcraft.notebooks.MAX_PER_PERSON", 2)
    store = NotebookStore(Database(tmp_path / "db.sqlite3"))
    _title, notebook = templates.blank_notebook()
    names = [store.create("vera", "Study", notebook)["name"] for _ in range(3)]
    assert names == ["Study.ipynb", "Study 2.ipynb", "Study 3.ipynb"]
    assert [item["name"] for item in store.list("vera")] == ["Study 3.ipynb", "Study 2.ipynb"]


def test_the_examples_run_on_any_installation(app, dist, monkeypatch):  # noqa: F811
    """Every example is copied into the person's folder and its cells run against this plant."""

    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with TestClient(app):
        _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        listed = vera.get("/api/notebooks").json()["examples"]
        assert [item["id"] for item in listed] == list(templates.EXAMPLES)
        assert (
            vera.post("/api/notebooks", json={"kind": "example", "example": "x"}).status_code == 422
        )
        token = vera.post("/api/assistant-access/mine", json={"label": "examples"}).json()["token"]
        monkeypatch.setattr(pc.Client, "_fetch", _routed(TestClient(app)))
        pc.connect("http://testserver", token=token)
        for item in listed:
            created = vera.post("/api/notebooks", json={"kind": "example", "example": item["id"]})
            assert created.status_code == 201, created.text
            # It opens from the Examples folder: no copy in My notebooks.
            assert created.json()["path"] == f"Examples/PlantCraft/{item['title']}.ipynb"
            notebook = vera.get(f"/notebooks/lite/files/{created.json()['path']}").json()
            assert item["title"] in notebook["cells"][0]["source"]
            space = {"pc": pc, "pd": pd, "plt": plt}
            # The second cell installs the package (%pip) in the browser: here it is imported.
            for cell in notebook["cells"][2:]:
                if cell["cell_type"] == "code":
                    exec(cell["source"], space)  # noqa: S102
            plt.close("all")
        folder = vera.get("/notebooks/lite/api/contents/all.json").json()
        assert (
            vera.get("/notebooks/lite/api/contents/My notebooks/all.json").json()["content"] == []
        )
    # A folder is dated by its newest notebook, never 1970 ("modified 56 years ago").
    assert not folder["last_modified"].startswith("1970")
    assert not folder["content"][0]["last_modified"].startswith("1970")


def test_every_example_has_a_title_of_its_own():
    titles = [item["title"] for item in templates.examples()]
    assert len(titles) == len(set(titles))


def test_the_copies_the_old_example_cards_wrote_are_dropped(tmp_path):
    """Before 2026-10-25 each click on an example card wrote "Example - ... 2", "... 3"."""

    from plantcraft.db import Database
    from plantcraft.notebooks import _drop_example_copies

    store = NotebookStore(Database(tmp_path / "pc.db"))
    notebook = templates.blank_notebook()[1]
    for _ in range(3):
        store.create("vera", f"Example - {templates.OLD_EXAMPLE_TITLES[0]}", notebook)
    store.create("vera", "My analysis", templates.blank_notebook()[1])
    assert len(store.list("vera")) == 4
    with store._write() as connection:
        _drop_example_copies(connection)
    assert [item["name"] for item in store.list("vera")] == ["My analysis.ipynb"]


def test_the_binary_answer_reads_as_the_json_one():
    import numpy as np

    from plantcraft_sdk import wire

    stamps = np.array([1_760_000_000_000, 1_760_000_000_250, 1_760_000_001_000], dtype=np.int64)
    writer = wire.BinaryWriter()
    writer.numbers("plant:A", "number", stamps, np.array([1.5, np.nan, -2.0]))
    writer.labels("plant:MODE", "text", stamps[:2], ["AUTO", None])
    as_json = {
        "series": [
            {
                "signal": "plant:A",
                "kind": "number",
                "t": [
                    "2025-10-09T08:53:20+00:00",
                    "2025-10-09T08:53:20.250000+00:00",
                    "2025-10-09T08:53:21+00:00",
                ],
                "v": [1.5, None, -2.0],
            },
            {
                "signal": "plant:MODE",
                "kind": "text",
                "t": ["2025-10-09T08:53:20+00:00", "2025-10-09T08:53:20.250000+00:00"],
                "v": ["AUTO", None],
            },
        ],
        "errors": [],
    }
    for binary, text in zip(pc._binary_columns(writer.body([])), pc._columns(as_json), strict=True):
        pd.testing.assert_series_equal(binary, text, check_dtype=binary.name != "plant:MODE")
    with pytest.raises(pc.PlantCraftError):
        pc._binary_columns(b"JSON")
