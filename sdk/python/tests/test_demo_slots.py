"""An isolated public demo visit works on its own copy of the app's database."""

import base64
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from plantcraft_sdk.server import demo_slots
from plantcraft_sdk.server.access import CurrentUser
from plantcraft_sdk.server.files import AppFiles
from plantcraft_sdk.server.store import Database, Store
from plantcraft_sdk.server.web import mount, suite_api
from plantcraft_sdk.testing import FakePlantCraft


class Notes(Store):
    SCHEMA = "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL);"

    def add(self, text: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO notes (text) VALUES (?)", (text,))

    def texts(self) -> list[str]:
        with self._connect() as connection:
            return [row["text"] for row in connection.execute("SELECT text FROM notes ORDER BY id")]


class Counters(Notes):
    SCHEMA = "CREATE TABLE IF NOT EXISTS counters (id INTEGER PRIMARY KEY, text TEXT NOT NULL);"
    DEMO_SHARED = True

    def add(self, text: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO counters (text) VALUES (?)", (text,))

    def texts(self) -> list[str]:
        with self._connect() as connection:
            return [r["text"] for r in connection.execute("SELECT text FROM counters ORDER BY id")]


def _visit(name: str, isolated: bool = True) -> dict:
    claim = {"visit": name, "ends": 2_000_000_000, "queries": 4, "queries_total": 8}
    if isolated:
        claim["isolated"] = True
    return claim


@pytest.fixture()
def app(tmp_path):
    db = Database(tmp_path / "data" / "app.sqlite3")
    notes, counters = Notes(db), Counters(db)
    notes.add("seeded")
    router = APIRouter()

    @router.get("/api/notes")
    def read(_user: CurrentUser) -> dict:
        return {"notes": notes.texts(), "counters": counters.texts()}

    @router.post("/api/notes")
    def write(_user: CurrentUser) -> dict:
        notes.add("visitor")
        counters.add("asked")
        return {"ok": True}

    fake = FakePlantCraft()
    (tmp_path / "app.toml").write_text('[app]\nid = "demoapp"\nname = "Demo"\n')
    runtime = SimpleNamespace(
        settings=SimpleNamespace(root_path="/demo", processcraft_public_url="/"),
        verifier=fake.verifier("linkcraft"),
        shutdown=lambda: None,
    )
    api = suite_api(
        runtime,
        title="Demo",
        version="0.1.0",
        files=AppFiles("demoapp", tmp_path),
        routers=[router],
        status_route=False,
    )
    return SimpleNamespace(
        fake=fake, http=TestClient(mount(api, runtime, version="0.1.0")), db=db, notes=notes
    )


def _as(app, visit: dict | None = None) -> dict:
    token = app.fake.token("operator", demo=visit) if visit else app.fake.token("operator")
    return {"Authorization": f"Bearer {token}"}


def test_a_visit_writes_to_its_own_copy(app):
    first, second = _as(app, _visit("v1")), _as(app, _visit("v2"))
    assert app.http.post("/demo/api/notes", headers=first).is_success
    # The visit sees its change, on top of what the demo started with.
    assert app.http.get("/demo/api/notes", headers=first).json()["notes"] == ["seeded", "visitor"]
    # Another visit and everyone else do not.
    assert app.http.get("/demo/api/notes", headers=second).json()["notes"] == ["seeded"]
    assert app.http.get("/demo/api/notes", headers=_as(app)).json()["notes"] == ["seeded"]
    assert app.notes.texts() == ["seeded"]
    copy = demo_slots.slot_path(app.db.path, demo_slots.key_of("v1"))
    assert copy.exists() and "v1" not in str(copy)


def test_a_shared_store_stays_on_the_apps_file(app):
    visitor = _as(app, _visit("v1"))
    app.http.post("/demo/api/notes", headers=visitor)
    # Counters a reset must not zero: on the app's own file, seen by everyone.
    assert app.http.get("/demo/api/notes", headers=_as(app)).json()["counters"] == ["asked"]


def test_a_visit_not_isolated_reads_the_apps_file(app):
    visitor = _as(app, _visit("v1", isolated=False))
    app.http.post("/demo/api/notes", headers=visitor)
    assert app.notes.texts() == ["seeded", "visitor"]
    assert not (app.db.path.parent / demo_slots.FOLDER).exists()


def test_a_forged_claim_picks_no_copy(app):
    token = app.fake.token("operator", demo=_visit("v1", isolated=False))
    head, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["demo"]["isolated"] = True
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    answer = app.http.get(
        "/demo/api/notes", headers={"Authorization": f"Bearer {head}.{forged}.{signature}"}
    )
    assert answer.status_code == 401
    assert not (app.db.path.parent / demo_slots.FOLDER).exists()


def test_too_large_a_database_is_never_copied(app, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_DEMO_SLOT_MAX_MB", "0")
    assert app.http.get("/demo/api/notes", headers=_as(app, _visit("v1"))).is_success
    assert not (app.db.path.parent / demo_slots.FOLDER).exists()


def test_old_copies_are_swept(app):
    app.http.get("/demo/api/notes", headers=_as(app, _visit("v1")))
    root = app.db.path.parent / demo_slots.FOLDER
    assert demo_slots.sweep(root, now=time.time()) == 0
    assert demo_slots.sweep(root, now=time.time() + 46 * 60) == 1
    assert list(root.iterdir()) == []


def test_work_carried_out_of_the_request_uses_the_visits_copy(app):
    key = demo_slots.key_of("v9")
    with demo_slots.using(key):
        app.notes.add("from a queue")
        assert app.notes.texts() == ["seeded", "from a queue"]
    assert app.notes.texts() == ["seeded"]
    with pytest.raises(ValueError):
        with demo_slots.using("../../etc"):
            pass


def test_an_isolated_visit_saves_only_in_an_app_that_copies(tmp_path):
    from plantcraft_sdk.server.access import Access

    db = Database(tmp_path / "data" / "app.sqlite3")
    notes = Notes(db)
    copying, keeping = Access("Copies", demo_copy=True), Access("Keeps")
    router = APIRouter()

    @router.post("/api/copies")
    def save_copy(_user: copying.EditorUser) -> dict:
        notes.add("saved")
        return {"notes": notes.texts()}

    @router.post("/api/keeps")
    def save_keep(_user: keeping.EditorUser) -> dict:
        return {"ok": True}

    fake = FakePlantCraft()
    (tmp_path / "app.toml").write_text('[app]\nid = "demoapp"\nname = "Demo"\n')
    runtime = SimpleNamespace(
        settings=SimpleNamespace(root_path="/demo", processcraft_public_url="/"),
        verifier=fake.verifier("linkcraft"),
        shutdown=lambda: None,
    )
    api = suite_api(
        runtime,
        title="Demo",
        version="0.1.0",
        files=AppFiles("demoapp", tmp_path),
        routers=[router],
        status_route=False,
    )
    http = TestClient(mount(api, runtime, version="0.1.0"))
    isolated = {"Authorization": f"Bearer {fake.token('operator', demo=_visit('v1'))}"}
    shared = {"Authorization": f"Bearer {fake.token('operator', demo=_visit('v2', False))}"}
    saved = http.post("/demo/api/copies", headers=isolated)
    assert saved.status_code == 200 and saved.json()["notes"] == ["saved"]
    assert notes.texts() == []
    # An app that did not say it copies, or a visit not isolated: nothing is saved, as before.
    assert http.post("/demo/api/keeps", headers=isolated).status_code == 403
    assert http.post("/demo/api/copies", headers=shared).status_code == 403


def test_a_visits_writes_to_plantcraft_with_the_apps_key_are_refused():
    from plantcraft_sdk.client import DemoVisitWrite, _demo_visit_write

    assert not _demo_visit_write("POST", "/api/v1/events")
    with demo_slots.using(demo_slots.key_of("v1")):
        assert _demo_visit_write("POST", "/api/v1/events")
        assert _demo_visit_write("PUT", "/api/v1/schedules")
        assert _demo_visit_write("PUT", "/api/v1/series")
        # Reads that are not a GET still go.
        assert not _demo_visit_write("POST", "/api/v1/series")
        assert not _demo_visit_write("POST", "/api/v1/llm/assistant")
    assert issubclass(DemoVisitWrite, Exception)
