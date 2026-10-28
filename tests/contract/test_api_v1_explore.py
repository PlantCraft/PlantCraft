"""API v1 Explorer (docs/api-v1.md, "Explorer"): the plant as folders, each asset with its
signals, the series apps computed about it and the events that named it; and a search that
lands on a value with its path. Readers only; nothing reads a series."""

from __future__ import annotations

from tests.contract.test_api_v1 import _as
from tests.contract.test_api_v1_links import _service


def test_the_plant_opens_asset_by_asset(central):
    reader = _as(central, "op")
    top = central.get("/api/v1/explore", headers=reader)
    assert top.status_code == 200, top.text
    roots = top.json()["children"]
    assert roots and all({"id", "name", "kind", "children", "roles"} <= set(row) for row in roots)
    # Down the tree to an asset with signals.
    assets = central.get("/api/v1/assets", headers=reader).json()
    held = next(item for item in assets if item["signals"])
    found = central.get("/api/v1/explore", params={"asset": held["id"]}, headers=reader).json()
    assert found["asset"]["id"] == held["id"] and found["path"][-1]["id"] == held["id"]
    assert {row["role"] for row in found["signals"]} == set(held["signals"])
    assert all({"id", "name", "unit", "kind"} <= set(row) for row in found["signals"])
    assert found["outputs"] == [] and found["events"] == []
    missing = central.get("/api/v1/explore", params={"asset": "no-such"}, headers=reader)
    assert missing.status_code == 404


def test_an_asset_shows_the_events_that_named_it_open_conditions_first(central):
    headers, reader = _service(central), _as(central, "op")
    asset = central.get("/api/v1/assets", headers=reader).json()[0]["id"]
    subject = f"asset:{asset}"
    central.post(
        "/api/v1/events",
        json=[
            {"kind": "linkcraft.run.failed", "subject": subject},
            {"kind": "linkcraft.finding.opened", "subject": subject, "phase": "start",
             "key": "a/osc", "severity": "warning"},
            {"kind": "linkcraft.finding.opened", "subject": subject, "phase": "start",
             "key": "a/sti", "severity": "warning"},
            {"kind": "linkcraft.finding.closed", "subject": subject, "phase": "end", "key": "a/sti"},
        ],
        headers=headers,
    )  # fmt: skip
    events = central.get("/api/v1/explore", params={"asset": asset}, headers=reader).json()[
        "events"
    ]
    assert events[0]["kind"] == "linkcraft.finding.opened" and events[0]["open"] == 1
    assert events[0]["count"] == 2 and events[0]["title"]
    assert {item["kind"] for item in events} == {
        "linkcraft.finding.opened",
        "linkcraft.finding.closed",
        "linkcraft.run.failed",
    }


def test_words_find_assets_and_signals_with_their_path(central):
    reader = _as(central, "op")
    assets = central.get("/api/v1/assets", headers=reader).json()
    held = next(item for item in assets if item["signals"])
    role, signal_id = next(iter(held["signals"].items()))
    hits = central.get(
        "/api/v1/explore", params={"q": f"{held['name']} {role}"}, headers=reader
    ).json()["hits"]
    signal = next(hit for hit in hits if hit["type"] == "signal" and hit["id"] == signal_id)
    assert signal["role"] == role and signal["path"][-1]["id"] == held["id"]
    named = central.get("/api/v1/explore", params={"q": held["id"]}, headers=reader).json()
    assert any(hit["type"] == "asset" and hit["id"] == held["id"] for hit in named["hits"])
    assert central.get("/api/v1/explore", params={"q": "zzz-nothing"}, headers=reader).json() == {
        "hits": []
    }


def test_the_explorer_needs_a_reader(central):
    assert central.get("/api/v1/explore").status_code == 401


def test_an_asset_shows_the_series_apps_computed_about_it(central):
    reader = _as(central, "op")
    asset = central.get("/api/v1/assets", headers=reader).json()[0]
    health = {
        "signal": f"app-linkcraft:{asset['id']}.valve.health",
        "name": "Valve health",
        "unit": "/100",
        "subject": f"asset:{asset['id']}",
        "result": "loop_health",
        "t": ["2026-10-19T07:00:00Z"],
        "v": [42.0],
    }
    assert (
        central.put("/api/v1/series", json=[health], headers=_service(central)).status_code == 200
    )
    found = central.get("/api/v1/explore", params={"asset": asset["id"]}, headers=reader).json()
    (output,) = found["outputs"]
    assert output["id"] == health["signal"] and output["app"] == "linkcraft"
    assert output["app_name"] and output["unit"] == "/100" and output["name"] == "Valve health"
    hits = central.get(
        "/api/v1/explore", params={"q": f"{asset['name']} valve health"}, headers=reader
    ).json()["hits"]
    assert [hit["id"] for hit in hits if hit["type"] == "output"] == [health["signal"]]
