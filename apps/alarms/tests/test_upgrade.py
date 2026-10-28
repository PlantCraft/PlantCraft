"""A database from an older release opens: each store's ``MIGRATIONS`` add what it lacks
(``plantcraft_sdk.apptest.upgrade_problems``, PlantCraft scale review E10)."""

from __future__ import annotations

import pytest
from plantcraft_sdk import apptest

from alarmcraft.alarms.incoming import IncomingStore
from alarmcraft.alarms.notices import NoticeStore
from alarmcraft.alarms.store import AlarmStore


@pytest.mark.parametrize("store", [AlarmStore, NoticeStore, IncomingStore])
def test_an_older_database_opens(tmp_path, store):
    assert not apptest.upgrade_problems(store, store, tmp_path)


def test_the_policies_of_an_older_alarms_are_dropped(tmp_path):
    # Every alarm has a rule now, and each rule says who hears: the old policies table goes.
    from plantcraft_sdk.server.store import Database

    db = Database(tmp_path / "alarmcraft.sqlite3")
    with db.connect() as connection:
        connection.execute("CREATE TABLE policies (policy_id TEXT PRIMARY KEY, config_json TEXT)")
    NoticeStore(db)
    with db.connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "policies" not in tables and "outbox" in tables
