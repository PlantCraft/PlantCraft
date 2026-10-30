"""An OPC UA server added at runtime next to the scenario's source, as the offline install does.

The deploy's scenario (``deploy/site/site.json``) has no data of its own; the administrator adds
The Simulator as a source and imports the plant map. These tests run that set-up against the test
server in ``tests/opcua_plant.py``: the kinds of its signals (a mode is text), its text series,
and a map preview that checks its tags from inside the API.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.config import LoopConfig
from tests.opcua_plant import NAMESPACE_URI, FakePlantCraft

pytest.importorskip("asyncua")

ROOT = Path(__file__).resolve().parents[1]
LOOP = "FIC-9001"
PV, MODE = f"CPM.Loops.{LOOP}.PV", f"CPM.Loops.{LOOP}.MODE"


@pytest.fixture(scope="module")
def plant():
    loop = LoopConfig(
        loop_id=LOOP,
        name="Test flow",
        signals={
            "pv": PV,
            "sp": f"CPM.Loops.{LOOP}.SP",
            "op": f"CPM.Loops.{LOOP}.OP",
            "mode": MODE,
        },
    )
    with FakePlantCraft([loop]) as server:
        yield server


@pytest.fixture()
def client(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "deploy" / "site" / "site.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / "deploy" / "site" / "no-data.csv")
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def _add_plant(client, plant) -> str:
    response = client.post(
        "/api/data/sources",
        json={
            "name": "Simulator",
            "type": "opcua",
            "settings": {"endpoint_url": plant.endpoint, "namespace_uri": NAMESPACE_URI},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["source_id"]


def _v1(client) -> dict[str, str]:
    token = client.post("/api/v1/auth/token").json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_a_mode_of_an_added_source_is_text_with_its_labels(client, plant):
    source = _add_plant(client, plant)
    used = client.post(f"/api/data/sources/{source}/signals/use", json={"tags": [PV, MODE]})
    assert used.status_code == 200, used.text
    headers = _v1(client)
    listed = {item["id"]: item for item in client.get("/api/v1/signals", headers=headers).json()}
    assert listed[f"{source}:{MODE}"]["kind"] == "text"
    assert listed[f"{source}:{PV}"]["kind"] == "number"

    end = datetime.now(timezone.utc)
    window = {"start": (end - timedelta(minutes=8)).isoformat(), "end": end.isoformat()}
    series = client.get(
        f"/api/v1/signals/{source}:{MODE}/series", params=window, headers=headers
    ).json()
    assert series["kind"] == "text"
    assert series["v"] and set(series["v"]) == {"AUTO"}
    batch = client.post(
        "/api/v1/series",
        json={"signals": [f"{source}:{MODE}", f"{source}:{PV}"], **window},
        headers=headers,
    ).json()
    kinds = {item["signal"]: (item["kind"], set(map(type, item["v"]))) for item in batch["series"]}
    assert kinds[f"{source}:{MODE}"] == ("text", {str})
    assert kinds[f"{source}:{PV}"][0] == "number" and kinds[f"{source}:{PV}"][1] <= {float, int}
    value = client.get(
        f"/api/v1/signals/{source}:{MODE}/value", params={"window": "15m"}, headers=headers
    ).json()
    assert value["value"] == "AUTO"


def test_kinds_of_an_unreachable_source_fall_back_to_number_and_are_browsed_once(
    client, plant, monkeypatch
):
    source = _add_plant(client, plant)
    client.post(f"/api/data/sources/{source}/signals/use", json={"tags": [PV, MODE]})
    registry = client.app.state.runtime.platform.sources
    calls = []
    real = registry.data

    def counted(source_id):
        calls.append(source_id)
        return real(source_id)

    monkeypatch.setattr(registry, "data", counted)
    for _ in range(3):
        assert registry.signal_kinds(source)[MODE] == "text"
    assert calls == [source]

    def offline(source_id):
        raise ConnectionError("unreachable")

    registry._kinds.clear()
    monkeypatch.setattr(registry, "data", offline)
    catalog = client.app.state.runtime.platform.signal_catalog()
    assert catalog.signals[f"{source}:{MODE}"]["kind"] == "number"


def test_the_map_preview_checks_the_tags_of_an_added_opcua_source(client, plant):
    source = _add_plant(client, plant)
    payload = {
        "loops": [
            {
                "loop_id": LOOP,
                "name": "Test flow",
                "pv": PV,
                "mode": MODE,
                "op": "CPM.Loops.FIC-9001.MISSING",
                "loop_type": "flow",
            }
        ],
        "signals": [
            {"tag": tag, "source_id": source} for tag in (PV, MODE, "CPM.Loops.FIC-9001.MISSING")
        ],
    }
    for route in ("/api/map/preview", "/api/map/apply"):
        report = client.post(
            route, params={"filename": "map.json"}, content=json.dumps(payload).encode()
        ).json()
        messages = [issue["message"] for issue in report["issues"]]
        assert not any("Could not check" in message for message in messages), messages
        # The browse ran: only the tag the server does not have is reported.
        missing = [message for message in messages if "was not found in source" in message]
        assert missing and all("MISSING" in message for message in missing), messages
    assert (
        client.app.state.runtime.platform.workspace.assets.attributes(LOOP)["loop_type"] == "flow"
    )


def test_the_top_bar_names_the_added_source(client, plant):
    assert client.get("/api/home").json()["source"]["label"] == "CSV file"
    _add_plant(client, plant)
    source = client.get("/api/home").json()["source"]
    assert source["label"] == "Simulator" and source["names"] == ["Simulator"]
    assert source["type"] == "csv"
