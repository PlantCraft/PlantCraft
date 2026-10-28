"""Saved dashboards and public links."""

from __future__ import annotations

import json
import sqlite3

import pytest
from plantcraft_sdk.server.store import Database

from dashcraft.dashboards.store import Conflict, DashboardStore


@pytest.fixture
def store(tmp_path):
    return DashboardStore(Database(tmp_path / "t.sqlite3"))


def test_create_update_delete(store):
    created = store.create({"name": "A", "cards": [{"card_id": "x"}]}, "ana")
    assert created["cards"] == [{"card_id": "x"}] and created["created_by"] == "ana"
    saved = store.update(created["dashboard_id"], {"name": "B", "cards": []}, "bruno")
    assert saved["name"] == "B" and saved["updated_by"] == "bruno"
    assert [item["name"] for item in store.list()] == ["B"]
    assert store.delete(created["dashboard_id"])
    assert store.get(created["dashboard_id"]) is None
    assert store.update("nope", {"name": "C"}, "ana") is None


def test_a_save_on_top_of_someone_elses_is_a_conflict(store):
    created = store.create({"name": "A"}, "ana")
    opened = created["updated_at"]
    store.update(created["dashboard_id"], {"name": "by bruno"}, "bruno", base_updated_at=opened)
    with pytest.raises(Conflict) as conflict:
        store.update(created["dashboard_id"], {"name": "by ana"}, "ana", base_updated_at=opened)
    assert conflict.value.current["name"] == "by bruno"


def test_links_keep_only_a_hash_and_stop_when_revoked(store, tmp_path):
    created = store.create({"name": "A"}, "ana")
    share, token = store.create_share(created["dashboard_id"], "ana", " wall ")
    assert share["label"] == "wall"
    assert store.resolve_share(token) == created["dashboard_id"]
    with sqlite3.connect(tmp_path / "t.sqlite3") as connection:
        stored = [row[0] for row in connection.execute("SELECT token_hash FROM dashboard_shares")]
    assert token not in stored and len(stored[0]) == 64
    assert store.list()[0]["public_links"] == 1
    assert store.revoke_share(created["dashboard_id"], share["share_id"], "ana")
    assert store.resolve_share(token) is None
    assert not store.revoke_share(created["dashboard_id"], share["share_id"], "ana")
    assert store.resolve_share("") is None and store.resolve_share("x" * 500) is None


def test_deleting_a_dashboard_revokes_its_links(store):
    created = store.create({"name": "A"}, "ana")
    _, token = store.create_share(created["dashboard_id"], "ana")
    store.delete(created["dashboard_id"], "ana")
    assert store.resolve_share(token) is None


def test_saves_in_the_same_millisecond_still_conflict(store, monkeypatch):
    monkeypatch.setattr(store, "_now", lambda: "2026-10-01T12:00:00.000+00:00")
    created = store.create({"name": "A"}, "ana")
    first = store.update(created["dashboard_id"], {"name": "B"}, "bruno")
    assert first["updated_at"] > created["updated_at"]
    with pytest.raises(Conflict):
        store.update(
            created["dashboard_id"], {"name": "C"}, "ana", base_updated_at=created["updated_at"]
        )


def test_saved_heights_move_to_the_finer_grid_once(tmp_path):
    path = tmp_path / "old.sqlite3"
    # A dashboard saved before pages and the finer grid (heights 1 short, 2 tall).
    with sqlite3.connect(path) as connection:
        connection.executescript(DashboardStore.SCHEMA)
        connection.execute(
            "INSERT INTO dashboards (dashboard_id, name, cards_json, created_at, updated_at) "
            "VALUES ('d1', 'Old', ?, '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00')",
            ('[{"card_id": "a", "height": 1}, {"card_id": "b", "height": 2}]',),
        )
    store = DashboardStore(Database(path))
    old = store.get("d1")
    assert [card["height"] for card in old["cards"]] == [2, 4]
    assert old["pages"] == [] and old["page_seconds"] == 0 and "grid" not in old
    # The grid move keeps the time; the move to UTC (SDK 0.18.0) only rewrote its form.
    assert old["updated_at"] == "2026-10-01T00:00:00.000Z"
    # Saved again with the new grid, and opened again: not doubled twice.
    store.update("d1", {**old, "cards": [{"card_id": "a", "height": 1}]}, "ana")
    again = DashboardStore(Database(path))
    assert again.get("d1")["cards"] == [{"card_id": "a", "height": 1}]
    created = again.create({"name": "New", "cards": [{"card_id": "x", "height": 1}]}, "ana")
    assert DashboardStore(Database(path)).get(created["dashboard_id"])["cards"][0]["height"] == 1


def test_pages_are_saved_with_the_dashboard(store):
    pages = [{"page_id": "p1", "name": "One"}, {"page_id": "p2", "name": "Two"}]
    created = store.create({"name": "A", "pages": pages, "page_seconds": 30}, "ana")
    assert created["pages"] == pages and created["page_seconds"] == 30
    saved = store.update(created["dashboard_id"], {"name": "A", "pages": pages[:1]}, "ana")
    assert saved["pages"] == pages[:1] and saved["page_seconds"] == 0


def test_round_6_dashboards_move_to_the_round_7_shape_once(tmp_path):
    path = tmp_path / "round6.sqlite3"
    store = DashboardStore(Database(path))
    created = store.create({"name": "Loops", "context_kind": "loop", "cards": []}, "ana")
    old_cards = [
        {
            "card_id": "a",
            "kind": "kpi",
            "width": 8,
            "height": 2,
            "thresholds": {"high_alarm": 9},
            "items": [{"asset_id": "$context", "role": "pv"}],
        },
        {"card_id": "b", "kind": "spark", "width": 6, "height": 2, "decimals": 1, "items": []},
        {"card_id": "c", "kind": "gauge", "width": 4, "height": 2, "gauge_max": 50, "items": []},
    ]
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE dashboards SET cards_json = ?, variables_json = '[]', grid = 2",
            (json.dumps(old_cards),),
        )
    cards = DashboardStore(Database(path)).get(created["dashboard_id"])["cards"]
    assert [(card["kind"], card["x"], card["y"]) for card in cards] == [
        ("stat", 0, 0),
        ("stat", 0, 2),
        ("gauge", 8, 0),
    ]
    assert cards[0]["items"][0]["asset_id"] == "$asset"
    assert cards[0]["field"]["thresholds"]["steps"][-1] == {
        "value": 9,
        "color": "",
        "level": "alarm",
    }
    assert cards[1]["options"]["graph"] == "area" and cards[1]["field"]["decimals"] == 1
    assert cards[2]["field"]["max"] == 50 and "gauge_max" not in cards[2]
    again = DashboardStore(Database(path)).get(created["dashboard_id"])
    assert again["variables"] == [
        {"name": "asset", "label": "loop", "type": "asset", "asset_kind": "loop"}
    ]
    assert again["cards"] == cards
