"""Cards saved with bare tags still read, and move to API v1 signal ids (decision D2)."""

from __future__ import annotations

from plantcraft_sdk.client import PlantCraftError

from dashcraft.dashboards.model import Card
from dashcraft.query.cards import Reader, read_card
from dashcraft.query.signal_ids import signal_renames
from tests.conftest import kpi

SIGNALS = [{"id": "fake:FIC-101.PV"}, {"id": "a:TWIN.PV"}, {"id": "b:TWIN.PV"}, {"id": "a:X:Y"}]


def test_only_a_tag_one_source_has_is_renamed():
    stored = {"FIC-101.PV", "fake:FIC-101.PV", "TWIN.PV", "GONE.PV", "X:Y"}
    assert signal_renames(stored, SIGNALS) == {"FIC-101.PV": "fake:FIC-101.PV", "X:Y": "a:X:Y"}


def test_a_bare_tag_still_reads_until_the_freeze(fake):
    reader = Reader(fake.client(None, app="dashcraft", key="test-app-key"), clock=lambda: fake.now)
    row = read_card(reader, Card(**kpi(signal_id="FIC-101.PV")))["rows"][0]
    assert row["error"] is None and row["value"] is not None


def test_saved_cards_move_to_signal_ids_without_a_new_version(runtime):
    old = runtime.dashboards.create(
        {"name": "Old", "cards": [kpi("a", signal_id="FIC-101.PV"), kpi("b", signal_id="GONE.PV")]},
        "ana",
    )
    report = runtime.migrate_signal_ids()
    assert report == {"renamed": {"FIC-101.PV": "fake:FIC-101.PV"}, "dashboards": 1}
    moved = runtime.dashboards.get(old["dashboard_id"])
    assert [card["items"][0]["signal_id"] for card in moved["cards"]] == [
        "fake:FIC-101.PV",
        "GONE.PV",
    ]
    assert moved["updated_at"] == old["updated_at"]
    assert runtime.migrate_signal_ids() == {"renamed": {}, "dashboards": 0}


def test_processcraft_down_leaves_the_cards_as_they_were(runtime, monkeypatch):
    runtime.dashboards.create({"name": "Old", "cards": [kpi(signal_id="FIC-101.PV")]}, "ana")

    def down():
        raise PlantCraftError("unavailable", status_code=503)

    monkeypatch.setattr(runtime.service_client, "signals", down)
    report = runtime.migrate_signal_ids()
    assert report["renamed"] == {} and "error" in report
    assert runtime.dashboards.signal_ids() == {"FIC-101.PV"}
