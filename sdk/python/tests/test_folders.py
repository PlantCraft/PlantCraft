"""Folders for an app's own objects (plantcraft_sdk.server.folders, Models round 9 M5)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_server import _runtime

from plantcraft_sdk.server.access import Access
from plantcraft_sdk.server.folders import FolderStore, folders_router
from plantcraft_sdk.server.store import Database
from plantcraft_sdk.testing import FakePlantCraft


def _store(tmp_path):
    return FolderStore(Database(tmp_path / "app.db"), ("model", "study"))


def test_folders_hold_objects_by_kind_and_move_only_on_purpose(tmp_path):
    store = _store(tmp_path)
    runs = store.create("study", "Tuning", by="Ana")
    assert runs["count"] == 0 and runs["created_by"] == "Ana"
    store.create("model", "tuning", by="Ana")  # the same name in another kind is fine
    for bad in ("", "  ", "TUNING"):
        try:
            store.create("study", bad, by="Ana")
        except ValueError:
            continue
        raise AssertionError(bad)
    try:
        store.create("block", "Mine", by="Ana")
    except ValueError as exc:
        assert "block" in str(exc)
    place = store.move("study", "s1", runs["folder_id"], by="Bia")
    assert place["folder_id"] == runs["folder_id"] and place["moved_by"] == "Bia"
    assert store.list("study")[0]["count"] == 1
    try:
        store.move("model", "m1", runs["folder_id"], by="Bia")  # a folder of another kind
    except ValueError:
        pass
    else:
        raise AssertionError("moved into a folder of another kind")
    try:
        store.delete(runs["folder_id"])
    except ValueError:
        pass
    else:
        raise AssertionError("deleted a folder that holds a study")
    assert store.move("study", "s1", "", by="Bia") is None and store.items("study") == {}
    assert store.rename(runs["folder_id"], "Loops")["name"] == "Loops"
    store.move("study", "s1", runs["folder_id"], by="Bia")
    store.forget("study", "s1")
    store.delete(runs["folder_id"])
    assert store.list("study") == []


def test_a_subclass_names_its_kinds_and_shares_the_tables(tmp_path):
    class Folders(FolderStore):
        KINDS = ("block",)

    db = Database(tmp_path / "app.db")
    made = Folders(db).create("block", "Mine", by="Ana")
    assert FolderStore(db, ("block",)).get(made["folder_id"])["name"] == "Mine"


def test_the_router_lets_editors_make_and_move_and_audits_them(tmp_path):
    fake = FakePlantCraft()
    rt = _runtime(fake)
    rt.folders = _store(tmp_path)
    rt.audited = []
    rt.audit = lambda user, action, subject, detail=None: rt.audited.append((action, subject))
    known = {("study", "s1"), ("model", "lib/Tank")}
    app = FastAPI()
    app.state.runtime = rt
    app.include_router(
        folders_router(
            ("model", "study"),
            editor=Access("Demo").EditorUser,
            exists=lambda _rt, kind, item_id: (kind, item_id) in known,
        )
    )
    client = TestClient(app)
    editor = {"Authorization": f"Bearer {fake.token('ana', apps={'linkcraft': 'editor'})}"}
    viewer = {"Authorization": f"Bearer {fake.token('bia', apps={'linkcraft': 'viewer'})}"}

    assert client.get("/api/folders/block", headers=editor).status_code == 422
    assert client.post("/api/folders/study", json={"name": "A"}, headers=viewer).status_code == 403
    made = client.post("/api/folders/study", json={"name": "A"}, headers=editor).json()
    again = client.post("/api/folders/study", json={"name": "a"}, headers=editor)
    assert again.status_code == 422
    folder = made["folder_id"]
    assert (
        client.put(
            "/api/folders/model/items/lib/Tank", json={"folder_id": folder}, headers=editor
        ).status_code
        == 422
    )  # a study folder
    assert (
        client.put(
            "/api/folders/study/items/nope", json={"folder_id": folder}, headers=editor
        ).status_code
        == 404
    )
    moved = client.put("/api/folders/study/items/s1", json={"folder_id": folder}, headers=editor)
    assert moved.json()["place"]["folder_id"] == folder
    listed = client.get("/api/folders/study", headers=viewer).json()
    assert listed["folders"][0]["count"] == 1 and listed["items"]["s1"]["folder_id"] == folder
    assert client.delete(f"/api/folders/study/{folder}", headers=editor).status_code == 409
    assert (
        client.patch(f"/api/folders/model/{folder}", json={"name": "B"}, headers=editor).status_code
        == 404
    )
    assert (
        client.patch(f"/api/folders/study/{folder}", json={"name": "B"}, headers=editor).json()[
            "name"
        ]
        == "B"
    )
    client.put("/api/folders/study/items/s1", json={"folder_id": ""}, headers=editor)
    assert client.delete(f"/api/folders/study/{folder}", headers=editor).status_code == 204
    assert [action for action, _ in rt.audited] == [
        "folder.created",
        "folder.moved",
        "folder.moved",
        "folder.deleted",
    ]
