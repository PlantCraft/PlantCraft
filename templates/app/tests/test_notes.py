"""The app's own object: notes on the plant's assets, written by editors, read by everyone."""

from __future__ import annotations

from tests.conftest import client_for, note


def test_an_editor_writes_a_note_on_an_asset_and_everyone_reads_it(runtime, fake, client):
    created = client.post("/api/notes", json=note())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["asset_id"] == "FIC-1001" and body["created_by"] == "engineer"
    assert body["asset_name"]  # read from PlantCraft as the person
    [entry] = [item for item in fake.audit_log if item["action"] == "starter.note.created"]
    assert entry["subject"] == body["note_id"] and entry["username"] == "engineer"
    with client_for(runtime, fake, "operator") as operator:
        listed = operator.get("/api/notes", params={"asset": "FIC-1001"}).json()
    assert [row["note_id"] for row in listed] == [body["note_id"]]


def test_a_note_changes_and_goes(client):
    note_id = client.post("/api/notes", json=note()).json()["note_id"]
    changed = client.put(f"/api/notes/{note_id}", json=note(text="Fixed on 2026-10-23."))
    assert changed.status_code == 200 and changed.json()["text"] == "Fixed on 2026-10-23."
    assert client.delete(f"/api/notes/{note_id}").status_code == 204
    assert client.get(f"/api/notes/{note_id}").status_code == 404


def test_a_note_needs_an_asset_plantcraft_knows(client):
    answer = client.post("/api/notes", json=note(asset_id="nowhere"))
    assert answer.status_code == 422
    assert client.get("/api/notes").json() == []


def test_viewers_read_only(runtime, fake, client):
    note_id = client.post("/api/notes", json=note()).json()["note_id"]
    with client_for(runtime, fake, "operator") as operator:
        assert operator.post("/api/notes", json=note()).status_code == 403
        assert operator.delete(f"/api/notes/{note_id}").status_code == 403
        assert operator.get(f"/api/notes/{note_id}").status_code == 200


def test_people_without_access_see_nothing(runtime, fake):
    with client_for(runtime, fake, "outsider") as outsider:
        assert outsider.get("/api/notes").status_code == 403
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get("/api/notes").status_code == 401
