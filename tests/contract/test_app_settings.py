"""Setup › Apps: the installation settings an app declares in [[contributes.settings]], set by
an administrator and read by the app (``GET /api/v1/contributions/settings``).

The fixture ``central`` is the one of ``test_api_v1.py``: Link (``linkcraft``) at ``/link/``.
"""

from __future__ import annotations

from plantcraft_sdk.testing import FakePlantCraft
from tests.contract.test_api_v1 import ADMIN, PASSWORD, _as
from tests.contract.test_api_v1_links import _service

DECLARES = {
    "contributes": {
        "settings": [
            {"key": "workers", "title": "Workers", "type": "integer", "default": 2, "min": 1,
             "max": 8},
            {"key": "mode", "title": "Mode", "type": "choice", "options": ["fast", "careful"],
             "default": "fast"},
            {"key": "token", "title": "Vendor token", "secret": True},
        ],
        "setup": [{"title": "Sources", "path": "/link/setup/sources"}],
    }
}  # fmt: skip


def _admin(central) -> None:
    answer = central.post("/api/login", json={"username": ADMIN, "password": PASSWORD})
    assert answer.status_code == 200, answer.text


def test_an_administrator_sets_an_apps_settings_and_the_app_reads_them(central):
    headers = _service(central)
    assert central.put("/api/v1/contributions", json=DECLARES, headers=headers).status_code == 200
    read = central.get("/api/v1/contributions/settings", headers=headers)
    assert read.json() == {
        "app": "linkcraft",
        "values": {"workers": 2, "mode": "fast", "token": None},
    }
    _admin(central)
    [app] = central.get("/api/setup/apps").json()["apps"]
    assert app["app"] == "linkcraft" and app["pages"][0]["path"] == "/link/setup/sources"
    saved = central.put(
        "/api/setup/apps/linkcraft", json={"values": {"workers": 4, "token": "s3cret"}}
    )
    assert saved.status_code == 200, saved.text
    shown = {item["key"]: item for item in saved.json()["settings"]}
    assert shown["workers"]["value"] == 4 and shown["workers"]["changed"] is True
    # A secret is never sent back to a screen, only whether it is set.
    assert shown["token"]["value"] is None and shown["token"]["set"] is True
    assert "s3cret" not in central.get("/api/setup/apps").text
    values = central.get("/api/v1/contributions/settings", headers=headers).json()["values"]
    assert values == {"workers": 4, "mode": "fast", "token": "s3cret"}
    # null puts the default back.
    central.put("/api/setup/apps/linkcraft", json={"values": {"workers": None}})
    assert (
        central.get("/api/v1/contributions/settings", headers=headers).json()["values"]["workers"]
        == 2
    )


def test_a_value_outside_the_rules_or_a_person_reading_them_is_refused(central):
    central.put("/api/v1/contributions", json=DECLARES, headers=_service(central))
    _admin(central)
    for values in (
        {"workers": 9},
        {"workers": 1.5},
        {"mode": "slow"},
        {"nope": 1},
        {"workers": True},
    ):
        answer = central.put("/api/setup/apps/linkcraft", json={"values": values})
        assert answer.status_code == 422, values
    assert central.put("/api/setup/apps/ghost", json={"values": {}}).status_code == 404
    assert (
        central.get("/api/v1/contributions/settings", headers=_as(central, "eng")).status_code
        == 403
    )
    central.post("/api/logout")
    central.post("/api/login", json={"username": "eng", "password": "password-123"})
    assert central.get("/api/setup/apps").status_code == 403


def test_the_fake_gives_the_app_its_settings():
    fake = FakePlantCraft()
    client = fake.client(app="linkcraft", key=fake.app_keys["linkcraft"])
    client.put_contributions(DECLARES)
    assert client.app_settings() == {"workers": 2, "mode": "fast", "token": None}
    fake.links.settings["linkcraft"] = {"workers": 3}
    assert client.app_settings()["workers"] == 3
