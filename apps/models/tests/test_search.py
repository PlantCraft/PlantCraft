"""Models' part of the suite's search (Ctrl+K): its models and studies."""

from __future__ import annotations

from tests.conftest import TLC, example


def test_search_finds_models_on_their_page(client):
    project = example(client)
    body = client.get("/api/search", params={"q": "TankLevel", "limit": 20}).json()
    assert body["format"] == "plantcraft-search/1"
    found = next(item for item in body["items"] if item["type"] == "Model")
    assert found["title"] == "TankLevelControl"
    assert found["href"] == f"/models/{project['id']}/{TLC}"
    assert client.get("/api/search", params={"q": "zz no such"}).json()["items"] == []
