"""Copy as prompt: a Modelica class as a prompt for an AI assistant."""

from __future__ import annotations

import json

from plantcraft_sdk.prompts import MAX_CHARS

from tests.conftest import TLC, example


def test_a_class_prompt_carries_its_text_the_project_and_the_rules(client):
    project = example(client)
    params = {"project_id": project["id"], "name": TLC}
    answer = client.get("/api/prompts/class", params=params).json()
    text = answer["text"]
    assert answer["title"] == f"Model: {TLC}" and answer["chars"] <= MAX_CHARS
    assert "PlantCraft Models" in text and "Examples" in text
    first = answer["parts"][0]
    assert first["kind"] == "modelica" and first["content"].startswith("model TankLevelControl")
    assert first["content"].rstrip().endswith("end TankLevelControl;")
    outline = json.loads(answer["parts"][-1]["content"])
    assert TLC in {item["name"] for item in outline}
    assert f"Keep the class name ({TLC})" in text
    assert "External functions (C code) are turned off" in text
    extend = client.get("/api/prompts/class", params={**params, "question": "extend"}).json()
    assert "Extend this model" in extend["text"]


def test_unknown_projects_and_classes(client):
    project = example(client)
    missing = {"project_id": project["id"], "name": "PlantCraftExamples.Nope"}
    assert client.get("/api/prompts/class", params=missing).status_code == 404
    assert (
        client.get("/api/prompts/class", params={"project_id": "x", "name": TLC}).status_code == 404
    )
    assert (
        client.get("/api/prompts/class", params={"project_id": "x", "name": "1bad"}).status_code
        == 422
    )
