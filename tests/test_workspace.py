"""The workspace: one database holding the stores of PlantCraft."""

from __future__ import annotations

from plantcraft.platform.workspace import Workspace


def test_workspace_seeds_the_five_person_demo_team(tmp_path):
    store = Workspace(tmp_path / "workspace.sqlite3")

    users = store.users.list_users()

    assert [user["username"] for user in users] == [
        "ana.lima",
        "marina.costa",
        "rafael.souza",
        "carlos.menezes",
        "julia.prado",
    ]
    assert {user["role"] for user in users} >= {"Control engineering", "Operations"}


def test_real_installations_start_without_demo_users(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_DEMO_USERS", "false")
    store = Workspace(tmp_path / "workspace.sqlite3")
    assert store.users.list_users() == []


def test_workspace_counts_people_and_assets(tmp_path):
    store = Workspace(tmp_path / "workspace.sqlite3")
    store.assets.save("u-1", name="Unit 1", kind="unit")
    assert store.counts() == {"users": 5, "assets": 1}
