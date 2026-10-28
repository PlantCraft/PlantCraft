"""API v1 result assets (docs/api-v1.md, "Result assets").

An app's service token keeps a set of result assets, one per asset it records about (Link: one
per asset of a schedule), each holding the points it writes. Results the app stops listing are
ended, not removed; ``GET /api/v1/assets`` lists them only when asked. ``FakePlantCraft``
answers the same shapes.
"""

from __future__ import annotations

import pytest

from plantcraft_sdk.client import Forbidden
from plantcraft_sdk.testing import FakePlantCraft
from tests.contract.test_api_v1 import _as
from tests.contract.test_api_v1_derived import _service


def _parent(client) -> str:
    assets = client.get("/api/v1/assets", headers=_as(client, "eng")).json()
    return next(item["id"] for item in assets if item["kind"] == "loop")


def _result(parent: str, key: str = "daily", **fields) -> dict:
    return {
        "id": f"linkcraft.{parent}.{key}",
        "parent_id": parent,
        "name": f"{parent} · Daily review",
        "made_by": "schedule:daily",
        "points": [
            {"role": "health", "signal": f"app-linkcraft:{parent}.{key}.health", "unit": "/100"},
            {"role": "verdict", "signal": f"app-linkcraft:{parent}.{key}.verdict"},
        ],
        **fields,
    }


def test_an_app_keeps_result_assets_under_the_assets_they_are_about(central):
    parent = _parent(central)
    headers = _service(central)
    answer = central.put(
        "/api/v1/assets/results", json={"assets": [_result(parent)]}, headers=headers
    )
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"saved": 1, "ended": 0}
    reader = _as(central, "op")
    plain = central.get("/api/v1/assets", headers=reader).json()
    assert all(item["kind"] != "result" for item in plain)  # hidden unless asked
    listed = central.get("/api/v1/assets", params={"results": "true"}, headers=reader).json()
    [result] = [item for item in listed if item["kind"] == "result"]
    assert result["parent_id"] == parent and result["type_path"] == ["result"]
    assert result["signals"] == {
        "health": f"app-linkcraft:{parent}.daily.health",
        "verdict": f"app-linkcraft:{parent}.daily.verdict",
    }
    assert {key: result["attributes"][key] for key in ("app", "made_by", "state", "origin")} == {
        "app": "linkcraft",
        "made_by": "schedule:daily",
        "state": "active",
        "origin": "app:linkcraft",
    }
    by_type = central.get("/api/v1/assets", params={"kind": "result"}, headers=reader).json()
    assert [item["id"] for item in by_type] == [result["id"]]

    # Not listed any more: ended, kept with its points; listed again: active.
    other = _result(parent, "weekly")
    answer = central.put("/api/v1/assets/results", json={"assets": [other]}, headers=headers)
    assert answer.json() == {"saved": 1, "ended": 1}
    ended = central.get(f"/api/v1/assets/{result['id']}", headers=reader).json()
    assert ended["attributes"]["state"] == "ended" and ended["signals"] == result["signals"]
    central.put("/api/v1/assets/results", json={"assets": [_result(parent)]}, headers=headers)
    again = central.get(f"/api/v1/assets/{result['id']}", headers=reader).json()
    assert again["attributes"]["state"] == "active"

    removed = central.post(
        "/api/v1/assets/results/remove",
        json={"ids": [result["id"], other["id"], parent]},
        headers=headers,
    )
    assert removed.json() == {"removed": 2}  # the plant asset is not the app's
    assert central.get(f"/api/v1/assets/{parent}", headers=reader).status_code == 200
    assert central.get(f"/api/v1/assets/{result['id']}", headers=reader).status_code == 404


@pytest.mark.parametrize(
    ("change", "fault"),
    [
        ({"id": "dashcraft.x"}, "id is linkcraft.<name>"),
        ({"parent_id": "nowhere"}, "parent_id nowhere is not an asset"),
        ({"name": ""}, "name is required"),
        ({"points": [{"role": "health", "signal": "app-dashcraft:x"}]}, "points.signal"),
        ({"points": [{"role": "Health!", "signal": "app-linkcraft:x"}]}, "points.role"),
    ],
)
def test_broken_items_write_nothing(central, change, fault):
    parent = _parent(central)
    good = _result(parent, "good")
    answer = central.put(
        "/api/v1/assets/results",
        json={"assets": [good, _result(parent, **change)]},
        headers=_service(central),
    )
    assert answer.status_code == 422 and answer.json()["detail"].startswith("[1] ")
    assert fault in answer.json()["detail"]
    listed = central.get(
        "/api/v1/assets", params={"results": "true"}, headers=_as(central, "eng")
    ).json()
    assert all(item["kind"] != "result" for item in listed)


def test_results_hang_under_plant_assets_and_ids_are_not_taken_twice(central):
    parent = _parent(central)
    headers = _service(central)
    first = _result(parent)
    central.put("/api/v1/assets/results", json={"assets": [first]}, headers=headers)
    nested = _result(parent, "nested", parent_id=first["id"])
    answer = central.put(
        "/api/v1/assets/results", json={"assets": [first, nested]}, headers=headers
    )
    assert answer.status_code == 422 and "not under another result" in answer.json()["detail"]
    twice = central.put("/api/v1/assets/results", json={"assets": [first, first]}, headers=headers)
    assert twice.status_code == 422 and "listed twice" in twice.json()["detail"]


def test_only_an_apps_service_token_writes_results(central):
    parent = _parent(central)
    body = {"assets": [_result(parent)]}
    person = _as(central, "eng")
    assert central.put("/api/v1/assets/results", json=body, headers=person).status_code == 403
    remove = {"ids": [f"linkcraft.{parent}.daily"]}
    assert (
        central.post("/api/v1/assets/results/remove", json=remove, headers=person).status_code
        == 403
    )
    # Another app's token makes its own results, never linkcraft's.
    other = central.put("/api/v1/assets/results", json=body, headers=_service(central, "dashcraft"))
    assert other.status_code == 422


def test_the_client_and_the_fake_keep_result_assets_alike():
    fake = FakePlantCraft()
    client = fake.client(None, app="linkcraft", key="test-app-key")
    plant = client.assets()
    assert client.sync_result_assets([_result("fic-101")]) == {"saved": 1, "ended": 0}
    [result] = client.assets(kind="result")
    assert result["parent_id"] == "fic-101" and result["attributes"]["state"] == "active"
    assert result["signals"]["health"] == "app-linkcraft:fic-101.daily.health"
    assert client.assets() == plant  # hidden unless asked
    assert len(client.assets(results=True)) == len(plant) + 1
    assert client.sync_result_assets([]) == {"saved": 0, "ended": 1}
    assert client.assets(kind="result")[0]["attributes"]["state"] == "ended"
    assert client.remove_result_assets([result["id"], "fic-101"]) == {"removed": 1}
    assert client.assets(results=True) == plant
    person = fake.client("admin")
    with pytest.raises(Forbidden):
        person.sync_result_assets([_result("fic-101")])
