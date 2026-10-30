"""Every time in UTC (PlantCraft, 2026-10-23): the catalog's times in one form, whatever the
server's time zone, and those written before with the server's local offset rewritten once."""

from __future__ import annotations

import time

import pytest

from histcraft.catalog.models import SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.db import Database, utc_times
from tests.conftest import database


@pytest.fixture
def sao_paulo(monkeypatch):
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_the_catalog_writes_utc_whatever_the_servers_zone(tmp_path, sao_paulo):
    catalog = CatalogStore(database(tmp_path, "config"))
    catalog.save_source(SourceIn(id="pc", name="Plant", endpoint="opc.tcp://plc:4840"), create=True)
    with catalog._connect() as connection:
        row = connection.execute("SELECT created, updated FROM sources WHERE id = 'pc'").fetchone()
    for stamp in (row["created"], row["updated"]):
        assert stamp.endswith("Z") and len(stamp) == len("2026-10-23T14:05:09.123Z")


def test_old_local_times_are_rewritten_once(tmp_path):
    db = database(tmp_path, "config")
    catalog = CatalogStore(db)
    catalog.save_source(SourceIn(id="pc", name="Plant", endpoint="opc.tcp://plc:4840"), create=True)
    with catalog._connect() as connection:
        connection.execute(
            "UPDATE sources SET created = '2026-10-20T08:00:00-03:00', updated = 'never'"
        )
    assert utc_times(db, CatalogStore.TIMES) == 1
    with catalog._connect() as connection:
        row = connection.execute("SELECT created, updated FROM sources").fetchone()
    assert (row["created"], row["updated"]) == ("2026-10-20T11:00:00.000Z", "never")
    assert utc_times(db, CatalogStore.TIMES) == 0


def test_opening_an_old_database_rewrites_it(tmp_path):
    path = tmp_path / "config.sqlite3"
    CatalogStore(Database(path)).save_source(
        SourceIn(id="pc", name="Plant", endpoint="opc.tcp://plc:4840"), create=True
    )
    with Database(path).connect() as connection:
        connection.execute("UPDATE sources SET updated = '2026-10-20T08:00:00-03:00'")
    CatalogStore(Database(path))  # a new process opening the file
    with Database(path).connect() as connection:
        assert connection.execute("SELECT updated FROM sources").fetchone()["updated"] == (
            "2026-10-20T11:00:00.000Z"
        )
