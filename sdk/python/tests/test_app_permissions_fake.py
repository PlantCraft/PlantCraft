"""The fake holds an app's token to its [permissions] as PlantCraft does (scale review E4)."""

import pytest

from plantcraft_sdk import apptest, testing
from plantcraft_sdk.client import Forbidden, PlantCraftClient
from plantcraft_sdk.testing import FakePlantCraft


@pytest.fixture()
def client():
    fake = FakePlantCraft()
    testing.PERMISSIONS_USED.pop("linkcraft", None)
    with PlantCraftClient(
        "http://fake", app="linkcraft", key="test-app-key", http_client=fake.http_client()
    ) as connected:
        yield connected
    testing.PERMISSIONS_USED.pop("linkcraft", None)


def test_an_app_that_declared_nothing_is_not_held_but_its_use_is_recorded(client):
    assert client.signals()
    client.audit("checked", "x")
    assert testing.PERMISSIONS_USED["linkcraft"] >= {"read.signals", "write.audit"}


def test_an_app_is_held_to_what_its_contributions_declare(client):
    client.put_contributions({"app": "linkcraft", "permissions": ["read.signals"]})
    assert client.signals()
    with pytest.raises(Forbidden):
        client.audit("checked", "x")


def test_permission_problems_names_what_app_toml_misses(tmp_path, client):
    (tmp_path / "app.toml").write_text('[permissions]\nread = ["signals"]\nwrite = []\n')
    client.signals()
    client.audit("checked", "x")
    assert apptest.permission_problems(tmp_path, "linkcraft") == [
        "linkcraft uses write.audit but app.toml [permissions] does not declare it"
    ]
