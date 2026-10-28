"""The Explorer through the client and the fake (``plantcraft_sdk.explore``): the plant as
folders, an asset with its signals, the series apps computed and the events that named it, and
words that land on a value with its path."""

from __future__ import annotations

from plantcraft_sdk.explore import path, search
from plantcraft_sdk.testing import FakePlantCraft


def test_an_asset_opens_with_everything_the_suite_has_about_it():
    fake = FakePlantCraft()
    client = fake.client()
    top = client.explore()
    assert top["asset"] is None and top["children"]
    first = top["children"][0]
    opened = client.explore(first["id"])
    assert opened["path"][-1]["id"] == first["id"]
    held = next(item for item in fake.assets if item.get("signals"))
    found = client.explore(held["id"])
    assert {row["role"] for row in found["signals"]} == set(held["signals"])
    service = fake.client(None, app="linkcraft", key="test-app-key")
    service.post_events(
        [
            {"kind": "linkcraft.finding.opened", "subject": f"asset:{held['id']}",
             "phase": "start", "key": "k1", "severity": "warning"},
            {"kind": "linkcraft.run.failed", "subject": f"asset:{held['id']}"},
        ]
    )  # fmt: skip
    events = client.explore(held["id"])["events"]
    assert events[0]["kind"] == "linkcraft.finding.opened" and events[0]["open"] == 1
    hits = client.explore(q=f"{held['name']} {next(iter(held['signals']))}")["hits"]
    assert any(hit["type"] == "signal" for hit in hits)


def test_words_must_all_be_found_in_the_value_or_its_path():
    assets = [
        {"id": "u1", "name": "Unit 100", "kind": "area", "parent_id": None, "signals": {}},
        {"id": "fic", "name": "FIC-1001", "kind": "loop", "parent_id": "u1",
         "signals": {"pv": "s:FIC1001.PV"}},
    ]  # fmt: skip
    signals = [
        {"id": "s:FIC1001.PV", "name": "Flow", "unit": "m3/h"},
        {"id": "app-linkcraft:fic.valve.health", "name": "Valve health", "unit": "/100",
         "app": "linkcraft", "subject": "asset:fic"},
    ]  # fmt: skip
    assert path(assets[1], {item["id"]: item for item in assets}) == [
        {"id": "u1", "name": "Unit 100"},
        {"id": "fic", "name": "FIC-1001"},
    ]
    hits = search(assets, signals, "unit 100 health", apps={"linkcraft": "Link"})
    assert [(hit["type"], hit["id"]) for hit in hits] == [
        ("output", "app-linkcraft:fic.valve.health")
    ]
    assert hits[0]["app_name"] == "Link"
    assert [hit["id"] for hit in search(assets, signals, "fic pv")] == ["s:FIC1001.PV"]
    assert search(assets, signals, "   ") == []
