"""The shared app server: store, app files, access checks and the web application."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from plantcraft_sdk.client import Unauthorized
from plantcraft_sdk.server.access import Access
from plantcraft_sdk.server.files import AppFiles
from plantcraft_sdk.server.store import Database, Store, recorded_at
from plantcraft_sdk.server.web import mount, suite_api, ui_folder
from plantcraft_sdk.testing import FakePlantCraft


class Notes(Store):
    SCHEMA = "CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, at TEXT NOT NULL);"

    def add(self, note_id: str) -> str:
        at = self._now()
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO notes VALUES (?, ?)", (note_id, at))
        return at


def test_store_applies_its_schema_once_and_stamps_rows(tmp_path):
    db = Database(tmp_path / "app.db")
    notes = Notes(db)
    Notes(db)
    assert notes.add("a")
    with recorded_at(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)):
        stamped = notes.add("b")
    assert datetime.fromisoformat(stamped) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert Store._loads("not json", []) == [] and Store._loads('{"a": 1}', {}) == {"a": 1}


def _repo(root):
    (root / "docs" / "help").mkdir(parents=True)
    (root / "app.toml").write_text('[app]\nid = "demoapp"\nversion = "0.1.0"\n')
    (root / "docs" / "help" / "start.md").write_text("# Start here\n\nHello.")
    (root / "docs" / "help" / "zeta.md").write_text("No title")
    (root / "docs" / "help" / "alpha.md").write_text("# Alpha\n")
    return AppFiles("demoapp", root, help_categories={"start": "Getting started"})


def test_app_files_serve_manifest_and_help(tmp_path, monkeypatch):
    files = _repo(tmp_path)
    monkeypatch.setenv("DEMOAPP_REVISION", "abc123")
    assert files.meta() == {"app": {"id": "demoapp", "version": "0.1.0"}, "revision": "abc123"}
    assert [page["id"] for page in files.help_pages()] == ["start", "alpha", "zeta"]
    assert files.help_pages()[0] == {
        "id": "start",
        "title": "Start here",
        "category": "Getting started",
    }
    assert files.help_pages()[2]["title"] == "zeta"
    assert files.help_page("start")["markdown"].startswith("# Start here")
    assert files.help_page("../app") is None and files.help_page("missing") is None
    monkeypatch.setenv("DEMOAPP_APP_DIR", str(tmp_path / "elsewhere"))
    files.clear()
    assert files.manifest() == {} and files.help_pages() == []


def _runtime(fake: FakePlantCraft, root: str = "/demo"):
    return SimpleNamespace(
        settings=SimpleNamespace(root_path=root, processcraft_public_url="https://plant/"),
        verifier=fake.verifier("linkcraft"),
        status=lambda: {"items": 3},
        started=[],
        start=lambda: None,
        shutdown=lambda: None,
    )


ACCESS = Access("Demo")
router = APIRouter()


@router.post("/api/things")
def make_thing(user: ACCESS.EditorUser) -> dict:
    return {"by": user.username}


@router.get("/api/refused")
def refused() -> None:
    def read() -> None:
        raise Unauthorized("app key revoked", status_code=401)

    ACCESS.guarded(read, service=True)


@pytest.fixture()
def setup(tmp_path):
    fake = FakePlantCraft()
    files = _repo(tmp_path)
    dist = tmp_path / "frontend" / "dist"
    (dist / "static").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "static" / "app.js").write_text("console.log(1)")
    runtime = _runtime(fake)
    api = suite_api(
        runtime,
        title="Demo",
        version="0.1.0",
        files=files,
        routers=[router],
        ui=ui_folder("demoapp", tmp_path),
        me=lambda user: {"extra": user.is_admin},
        public_pages=("share/",),
    )
    app = mount(api, runtime, version="0.1.0")
    return fake, TestClient(app, follow_redirects=False)


def test_endpoints_every_app_serves(setup):
    fake, client = setup
    assert client.get("/healthz").json() == {"status": "ok", "version": "0.1.0"}
    assert client.get("/demo/healthz").status_code == 200
    assert client.get("/").headers["location"] == "/demo/"
    assert client.get("/demo/api/me").status_code == 401
    engineer = {"Authorization": f"Bearer {fake.token('engineer')}"}
    me = client.get("/demo/api/me", headers=engineer).json()
    assert me["username"] == "engineer" and me["role"] == "editor" and me["extra"] is False
    assert me["processcraft_url"] == "https://plant/"
    assert client.get("/demo/api/meta", headers=engineer).json()["app"]["id"] == "demoapp"
    assert len(client.get("/demo/api/help", headers=engineer).json()) == 3
    assert client.get("/demo/api/help/nope", headers=engineer).status_code == 404
    assert client.get("/demo/api/status", headers=engineer).json() == {
        "items": 3,
        "version": "0.1.0",
    }
    assert client.get("/demo/api/unknown", headers=engineer).status_code == 404


def test_editor_and_guarded_reads(setup):
    fake, client = setup
    operator = {"Authorization": f"Bearer {fake.token('operator')}"}
    engineer = {"Authorization": f"Bearer {fake.token('engineer')}"}
    denied = client.post("/demo/api/things", headers=operator)
    assert (
        denied.status_code == 403 and denied.json()["detail"] == "Your access to Demo is read-only."
    )
    assert client.post("/demo/api/things", headers=engineer).json() == {"by": "engineer"}
    refused = client.get("/demo/api/refused", headers=engineer)
    assert refused.status_code == 503 and "app key of Demo" in refused.json()["detail"]


def test_pages_need_a_sign_in_except_public_ones(setup):
    fake, client = setup
    page = client.get("/demo/loops", headers={"Accept": "text/html"})
    assert page.status_code == 303 and page.headers["location"].startswith(
        "/login?next=/demo/loops"
    )
    assert client.get("/demo/static/app.js").status_code == 200
    shared = client.get("/demo/share/abc")
    assert shared.status_code == 200 and shared.headers["cache-control"] == "no-store"
    client.cookies.set("processcraft_token", fake.token("operator"))
    assert client.get("/demo/loops").text == "<html>app</html>"


def test_health_fails_when_the_runtime_names_a_problem():
    runtime = _runtime(FakePlantCraft())
    problems = ["The engine process stopped 3 times."]
    runtime.health_problem = lambda: problems[0]
    client = TestClient(mount(APIRouter(), runtime, version="0.1.0"))
    answer = client.get("/healthz")
    assert answer.status_code == 503
    assert answer.json()["problem"] == "The engine process stopped 3 times."
    problems[0] = None
    assert client.get("/healthz").json() == {"status": "ok", "version": "0.1.0"}
