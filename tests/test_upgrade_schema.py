"""An installation of every published release opens with the current tables (scale review E10).

``tests/schemas/<version>.sql`` is the schema a fresh installation of that release had
(``dev/schema-snapshot/dump.py``, one per release). Each is opened with the current code: the
stores' ``MIGRATIONS`` must bring it to every table and column a fresh installation has now,
and opening it again runs nothing more.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = sorted((ROOT / "tests" / "schemas").glob("*.sql"))


def _open(database: Path, tmp_path: Path, monkeypatch) -> None:
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(database)
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / f"{database.stem}.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/,histcraft=/hist/")
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200


def _tables(database: Path) -> dict[str, set[str]]:
    with sqlite3.connect(database) as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            name: {row[1] for row in connection.execute(f"PRAGMA table_info({name})")}
            for name in names
        }


def _migrations(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sdk_migrations")}


@pytest.fixture()
def fresh(tmp_path, monkeypatch) -> dict[str, set[str]]:
    database = tmp_path / "fresh.sqlite3"
    _open(database, tmp_path, monkeypatch)
    return _tables(database)


def test_there_is_a_snapshot_of_a_published_release():
    assert any(path.stem == "0.4.0" for path in SNAPSHOTS)


@pytest.mark.parametrize("snapshot", SNAPSHOTS, ids=[path.stem for path in SNAPSHOTS])
def test_a_release_installation_upgrades_to_the_current_tables(
    snapshot, fresh, tmp_path, monkeypatch
):
    database = tmp_path / "upgraded.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(snapshot.read_text())
    _open(database, tmp_path, monkeypatch)
    upgraded = _tables(database)
    missing = {
        table: sorted(columns - upgraded.get(table, set()))
        for table, columns in fresh.items()
        if columns - upgraded.get(table, set())
    }
    assert missing == {}
    ran = _migrations(database)
    _open(database, tmp_path, monkeypatch)
    assert _migrations(database) == ran
