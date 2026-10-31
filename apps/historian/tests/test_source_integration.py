"""A source as an integration (H13): who answers for it, how to reach the team that runs it, how
often a value must arrive, and the history of its states."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from histcraft.archive.store import ArchiveStore, now_ms
from histcraft.catalog.models import SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.service import Collector
from histcraft.db import Database
from tests.conftest import make_settings

SOURCE = {"id": "plant", "name": "Plant", "kind": "opcua", "endpoint": "opc.tcp://127.0.0.1:4999"}


def test_the_api_keeps_owners_contact_and_interval_when_a_page_leaves_them_out(client):
    created = client.post(
        "/hist/api/sources",
        json={**SOURCE, "owners": ["Group:Automation", "user:ana", "user:ana"],
              "contact": "Automation team,\n ext. 4321", "heartbeat_seconds": 300},
    )  # fmt: skip
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["owners"] == ["group:automation", "user:ana"]
    assert body["contact"] == "Automation team, ext. 4321"
    assert body["heartbeat_seconds"] == 300
    # An older page (or client) sends the source without the integration: it stays.
    kept = client.put("/hist/api/sources/plant", json={**SOURCE, "name": "Plant A"}).json()
    assert kept["owners"] == ["group:automation", "user:ana"] and kept["heartbeat_seconds"] == 300
    cleared = client.put("/hist/api/sources/plant", json={**SOURCE, "heartbeat_seconds": 0})
    assert cleared.json()["heartbeat_seconds"] == 0 and cleared.json()["owners"]
    listed = next(item for item in client.get("/hist/api/sources").json() if item["id"] == "plant")
    assert listed["contact"] == "Automation team, ext. 4321"
    assert client.get("/hist/api/sources/plant/history").json() == []
    assert client.get("/hist/api/sources/nope/history").status_code == 404


@pytest.mark.parametrize(
    "fields",
    [{"owners": ["ana"]}, {"owners": ["everyone:all"]}, {"heartbeat_seconds": 30},
     {"heartbeat_seconds": -1}, {"owners": [f"user:u{n}" for n in range(21)]}],
)  # fmt: skip
def test_owners_are_people_or_groups_and_the_interval_at_least_a_minute(fields):
    with pytest.raises(ValidationError):
        SourceIn(**SOURCE, **fields)


def test_the_collector_writes_each_change_of_state_once(tmp_path):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    archive = ArchiveStore(Database(settings.archive_target))
    catalog.save_source(SourceIn(**SOURCE), create=True)
    collector = Collector(settings, catalog, archive)
    start = now_ms() - 60_000
    collector.source_status["plant"] = {"status": "connected", "detail": "", "since": start + 1000}
    collector.flush()
    collector.flush()  # the same state: nothing new
    collector.source_status["plant"] = {
        "status": "disconnected",
        "detail": "refused",
        "since": start + 2000,
    }
    collector.flush()
    # Each retry of a lost connection is still the same state.
    collector.source_status["plant"] = {
        "status": "disconnected",
        "detail": "refused",
        "since": start + 3000,
    }
    collector.flush()
    assert catalog.source_events("plant") == [
        {"at_ms": start + 2000, "status": "disconnected", "detail": "refused"},
        {"at_ms": start + 1000, "status": "connected", "detail": ""},
    ]
    # A restarted collector takes up where the history left off.
    again = Collector(settings, catalog, archive)
    again.source_status["plant"] = {
        "status": "disconnected",
        "detail": "refused",
        "since": start + 4000,
    }
    again.flush()
    assert len(catalog.source_events("plant")) == 2
    catalog.delete_source("plant")
    assert catalog.source_events("plant") == []
