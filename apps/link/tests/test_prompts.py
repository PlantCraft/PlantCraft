"""Copy as prompt: methods, blocks and algorithms as prompts for an AI assistant."""

from __future__ import annotations

import json

from plantcraft_sdk.prompts import MAX_CHARS


def test_a_method_prompt_carries_its_source_declaration_and_help(client):
    answer = client.get("/link/api/prompts/method/stiction_screening").json()
    text = answer["text"]
    assert answer["title"].startswith("Method: ") and answer["chars"] <= MAX_CHARS
    assert "PlantCraft Analytics" in text and "## Question" in text
    labels = [part["label"] for part in answer["parts"]]
    assert labels[0].startswith("Source (") and labels[1].startswith("Declaration")
    assert "def run" in answer["parts"][0]["content"] and answer["parts"][0]["kind"] == "python"
    declaration = json.loads(answer["parts"][1]["content"])
    assert declaration["method_id"] == "stiction_screening" and declaration["parameters"]
    assert "Keep the method id (stiction_screening)" in text
    adapt = client.get("/link/api/prompts/method/stiction_screening", params={"question": "adapt"})
    assert "adapt this method to my plant" in adapt.json()["text"]


def test_a_signal_check_and_the_unknown_ones(client):
    check = client.get("/link/api/prompts/method/sq_frozen").json()
    assert check["parts"][0]["kind"] == "python"
    assert client.get("/link/api/prompts/method/nope").status_code == 404
    assert client.get("/link/api/prompts/block/dq.nope").status_code == 404
    assert client.get("/link/api/prompts/algorithm/nope").status_code == 404


def test_block_and_algorithm_prompts(client):
    block = client.get("/link/api/prompts/block/dq.frozen").json()
    assert "Refer to blocks by their id (dq.frozen)" in block["text"]
    assert [part["kind"] for part in block["parts"]] == ["markdown", "json"]
    algorithm = client.get("/link/api/prompts/algorithm/loop_health").json()
    diagram = json.loads(algorithm["parts"][0]["content"])
    assert diagram["nodes"] and "edges" in diagram
    review = client.get("/link/api/prompts/algorithm/loop_health", params={"question": "review"})
    assert "corrected diagram" in review.json()["text"]
