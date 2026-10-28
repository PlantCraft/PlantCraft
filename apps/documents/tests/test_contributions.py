"""What PlantCraft Documents adds to PlantCraft (``app.toml [contributes]``): the Ctrl+K search,
what a ``#doc:<id>`` names, the widgets, and the assistant's tools and works."""

from __future__ import annotations

import tomllib
from pathlib import Path

from plantcraft_sdk import apptest
from plantcraft_sdk.app_manifest import parse_manifest

from tests.conftest import client_for, guide

ROOT = Path(__file__).resolve().parents[1]


def test_ctrl_k_finds_documents_by_number_and_passages_by_meaning(client, runtime):
    guide(client, runtime)
    answer = client.get("/api/search", params={"q": "DOC-TG-001"}).json()
    assert answer["items"][0]["type"] == "Document"
    passages = client.get("/api/search", params={"q": "valve stiction"}).json()["items"]
    assert any(item["type"] == "Passage" and "?passage=" in item["href"] for item in passages)


def test_a_reference_names_the_document_for_whoever_may_read_it(runtime, fake, client):
    doc = guide(client, runtime, revision="C")
    ref = client.get(f"/api/refs/doc/{doc['doc_id']}").json()
    assert ref == {
        "title": "DOC-TG-001 troubleshooting",
        "status": "Rev. C",
        "url": f"/doc/documents/{doc['doc_id']}",
    }
    folder = client.post("/api/folders", json={"name": "Kept", "viewers": ["user:engineer"]}).json()
    client.patch(f"/api/documents/{doc['doc_id']}", json={"folder_id": folder["folder_id"]})
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get(f"/api/refs/doc/{doc['doc_id']}").status_code == 404


def test_the_widgets_answer_in_the_shapes_app_toml_declares(client, runtime):
    guide(client, runtime)
    assert apptest.widget_problems(client, "") == []


def test_the_assistant_tools_match_the_routes_and_name_their_arguments():
    manifest = parse_manifest(tomllib.loads((ROOT / "app.toml").read_text(encoding="utf-8")))
    tools = {tool.id: tool for tool in manifest.contributes.assistant.tools}
    assert set(tools) == {"search_documents", "read_document", "find_tags"}
    assert [arg.key for arg in tools["search_documents"].args] == [
        "query",
        "asset",
        "kind",
        "limit",
    ]
    assert [arg.key for arg in tools["read_document"].args if arg.required] == ["document"]
    # Each work names the tools by the name the model sees: <app>_<tool>.
    for work in manifest.contributes.assistant.works:
        assert (
            "doccraft_search_documents" in work.instructions
            or "doccraft_read_document" in work.instructions
        )
