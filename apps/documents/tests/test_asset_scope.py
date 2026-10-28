"""A person who sees only part of the plant (PlantCraft's token claim ``assets``, its
docs/asset-scope.md) finds a document about assets (those a person linked) only when one of them
is in that part: the list, the page, the search and the assistant's tools. A document about no
asset is everyone's."""

from __future__ import annotations

import pytest
from plantcraft_sdk.asset_scope import forget

from tests.conftest import client_for, docx_bytes, guide, index, send


@pytest.fixture(autouse=True)
def _fresh():
    forget()
    yield
    forget()


def limited(runtime, fake, asset: str, username="engineer"):
    client = client_for(runtime, fake, None)
    client.headers["Authorization"] = f"Bearer {fake.token(username, assets=[asset])}"
    return client


def test_documents_about_other_assets_stay_out(client, runtime, fake):
    general = guide(client, runtime)
    startup = send(
        client, "start-up.docx", docx_bytes("Start-up", "Open the feed valve slowly: stiction.")
    )
    index(runtime)
    linked = client.put(f"/api/documents/{startup['doc_id']}/assets", json={"assets": ["FIC-1001"]})
    assert linked.status_code == 200, linked.text
    other = next(
        item["id"]
        for item in fake.assets
        if item.get("kind") == "loop" and item["id"] != "FIC-1001"
    )

    with limited(runtime, fake, other, "operator") as stranger:
        listed = {doc["doc_id"] for doc in stranger.get("/api/documents").json()}
        assert listed == {general["doc_id"]}
        assert stranger.get(f"/api/documents/{startup['doc_id']}").status_code == 404
        passages = stranger.post("/api/search", json={"query": "stiction valve"}).json()
        assert {p["ref"] for p in passages["passages"]} == {f"doc:{general['doc_id']}"}
        tools = stranger.post(
            "/api/assistant/tools/search_documents", json={"query": "open the feed valve"}
        ).json()
        assert all(p["ref"] != f"doc:{startup['doc_id']}" for p in tools["passages"])

    with limited(runtime, fake, "FIC-1001", "operator") as insider:
        assert insider.get(f"/api/documents/{startup['doc_id']}").status_code == 200
    assert {doc["doc_id"] for doc in client.get("/api/documents").json()} == {
        general["doc_id"],
        startup["doc_id"],
    }
