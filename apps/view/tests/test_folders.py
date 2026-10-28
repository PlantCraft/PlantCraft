"""Folders: who sees and edits their dashboards (people and platform groups), versions, the
New dashboard templates and the one-off clean-up of untouched copies."""

from __future__ import annotations

import sqlite3

from plantcraft_sdk.server.store import Database

from dashcraft.dashboards.store import DashboardStore
from tests.conftest import client_for, dashboard

# The fake's groups: "operations" (operator) and "process-engineering" (engineer, admin).


def _folder(client, **fields) -> dict:
    answer = client.post("/dash/api/folders", json={"name": "Instrumentation", **fields})
    assert answer.status_code == 201, answer.text
    return answer.json()


def _create(client, **fields) -> dict:
    answer = client.post("/dash/api/dashboards", json=dashboard(**fields))
    assert answer.status_code == 201, answer.text
    return answer.json()


def test_a_folder_kept_for_a_group_hides_its_dashboards_from_everyone_else(runtime, fake, client):
    folder = _folder(client, viewers=["group:process-engineering"])
    kept = _create(client, name="Valves", folder_id=folder["folder_id"])
    _create(client, name="Open to all")
    path = f"/dash/api/dashboards/{kept['dashboard_id']}"
    with client_for(runtime, fake, "operator") as operator:
        names = [item["name"] for item in operator.get("/dash/api/dashboards").json()]
        assert "Valves" not in names and "Open to all" in names
        assert operator.get(path).status_code == 404
        assert operator.get(f"{path}/cards/k1").status_code == 404
        assert operator.get("/dash/api/folders").json() == []
    assert client.get(path).status_code == 200
    with client_for(runtime, fake, "admin") as admin:
        assert admin.get(path).status_code == 200
    # Named one by one, a person sees it too.
    client.put(
        f"/dash/api/folders/{folder['folder_id']}",
        json={"name": "Instrumentation", "viewers": ["user:operator"]},
    )
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get(path).status_code == 200
        assert operator.get("/dash/api/folders").json()[0]["dashboards"] == 1


def test_only_the_folders_editors_change_or_add_its_dashboards(runtime, fake):
    with client_for(runtime, fake, "admin") as admin:
        folder = _folder(admin, editors=["user:admin"])
        kept = _create(admin, name="Valves", folder_id=folder["folder_id"])
    with client_for(runtime, fake, "engineer") as engineer:
        path = f"/dash/api/dashboards/{kept['dashboard_id']}"
        listed = engineer.get("/dash/api/dashboards").json()
        assert [item["can_edit"] for item in listed if item["name"] == "Valves"] == [False]
        assert engineer.put(path, json=dashboard(name="Mine")).status_code == 403
        assert engineer.delete(path).status_code == 403
        assert engineer.get(f"{path}/shares").status_code == 403
        added = engineer.post("/dash/api/dashboards", json=dashboard(folder_id=folder["folder_id"]))
        assert added.status_code == 403
        # A copy goes to General, where the engineer edits.
        copy = engineer.post(f"{path}/copy").json()
        assert copy["folder_id"] == "" and copy["can_edit"] is True
        missing = engineer.post("/dash/api/dashboards", json=dashboard(folder_id="nope"))
        assert missing.status_code == 422


def test_nobody_but_an_admin_takes_themselves_off_a_folder(runtime, fake, client):
    locked = client.post(
        "/dash/api/folders", json={"name": "Mine", "editors": ["group:operations"]}
    )
    assert locked.status_code == 422
    folder = _folder(client, editors=["group:process-engineering"])
    assert (
        client.put(
            f"/dash/api/folders/{folder['folder_id']}",
            json={"name": "X", "editors": ["user:admin"]},
        ).status_code
        == 422
    )
    assert client.post("/dash/api/folders", json={"name": "instrumentation"}).status_code == 409


def test_a_folder_is_deleted_only_when_empty_and_every_change_is_audited(fake, client):
    folder = _folder(client)
    kept = _create(client, folder_id=folder["folder_id"])
    path = f"/dash/api/folders/{folder['folder_id']}"
    assert client.delete(path).status_code == 409
    client.delete(f"/dash/api/dashboards/{kept['dashboard_id']}")
    assert client.delete(path).status_code == 204
    actions = [entry["action"] for entry in fake.audit_log]
    assert "dashcraft.folder.create" in actions and "dashcraft.folder.delete" in actions


def test_moving_a_dashboard_needs_the_target_folder(runtime, fake):
    with client_for(runtime, fake, "admin") as admin:
        closed = _folder(admin, name="Closed", editors=["user:admin"])
    with client_for(runtime, fake, "engineer") as engineer:
        mine = _create(engineer)
        moved = engineer.put(
            f"/dash/api/dashboards/{mine['dashboard_id']}",
            json=dashboard(folder_id=closed["folder_id"]),
        )
        assert moved.status_code == 403
        opened = _folder(engineer, name="Open")
        moved = engineer.put(
            f"/dash/api/dashboards/{mine['dashboard_id']}",
            json=dashboard(folder_id=opened["folder_id"], tags=["Unit 100", " unit 100 "]),
        )
        assert moved.status_code == 200
        assert moved.json()["folder_id"] == opened["folder_id"]
        assert moved.json()["tags"] == ["Unit 100"]


def test_versions_keep_every_save_and_restore_one(client):
    created = _create(client, name="First")
    path = f"/dash/api/dashboards/{created['dashboard_id']}"
    client.put(path, json=dashboard(name="Second", default_window="8h", shared_cursor=True))
    versions = client.get(f"{path}/versions").json()
    assert [item["name"] for item in versions] == ["Second", "First"]
    assert versions[0]["version"] == 2 and versions[0]["saved_by"] == "engineer"
    one = client.get(f"{path}/versions/1").json()
    assert one["dashboard"]["name"] == "First"
    restored = client.post(f"{path}/versions/1/restore").json()
    assert restored["name"] == "First" and restored["shared_cursor"] is False
    assert len(client.get(f"{path}/versions").json()) == 3
    assert client.get(f"{path}/versions/99").status_code == 404


def test_templates_save_nothing_and_the_old_starter_route_never_repeats(client):
    found = client.get("/dash/api/templates").json()
    assert [item["template_id"] for item in found] == ["loop-detail", "unit-overview"]
    assert found[0]["draft"]["context_kind"] == "loop"
    assert [item["name"] for item in client.get("/dash/api/dashboards").json()] == []
    first = client.post("/dash/api/dashboards/starter").json()
    again = client.post("/dash/api/dashboards/starter").json()
    assert len(first) == 2 and again == []


def test_untouched_copies_and_empty_new_dashboards_are_removed_once(tmp_path):
    path = tmp_path / "t.sqlite3"
    store = DashboardStore(Database(path))
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM dashboard_marks")
    kept = store.create({"name": "Loop detail", "cards": [{"card_id": "a"}]}, "ana")
    store.create({"name": "Loop detail", "cards": [{"card_id": "a"}]}, "ana")
    changed = store.create({"name": "Loop detail", "cards": [{"card_id": "a"}]}, "ana")
    store.update(
        changed["dashboard_id"], {"name": "Loop detail", "cards": [{"card_id": "a"}]}, "bo"
    )
    store.create({"name": "New dashboard"}, "ana")
    shared = store.create({"name": "New dashboard"}, "ana")
    store.create_share(shared["dashboard_id"], "ana")
    store = DashboardStore(Database(path))
    ids = {item["dashboard_id"] for item in store.list()}
    assert ids == {kept["dashboard_id"], changed["dashboard_id"], shared["dashboard_id"]}
    store.create({"name": "New dashboard"}, "ana")
    assert len(DashboardStore(Database(path)).list()) == 4


def test_a_folder_that_no_longer_exists_keeps_its_dashboards_for_administrators():
    """The same rule as Documents' folders (platform review I1, 2026-10-27)."""

    from dashcraft.api.deps import Permissions

    person = Permissions(username="engineer", admin=False, editor=True)
    admin = Permissions(username="admin", admin=True, editor=True)
    assert not person.sees_folder("gone") and not person.edits_folder("gone")
    assert admin.sees_folder("gone") and admin.edits_folder("gone")
    assert person.sees_folder("") and person.edits_folder("")
