"""A diagram drafted by the model PlantCraft gives View's use ``diagram-draft``: the model gets the
format, the symbols and the unit's assets; its answer is checked, repaired and never saved."""

from __future__ import annotations

import json

import pytest
from plantcraft_sdk.client import PlantCraftError

from dashcraft.diagrams.draft import COMMON_SYMBOLS, candidates, read_answer
from dashcraft.diagrams.model import DiagramPayload
from dashcraft.diagrams.symbols import library
from tests.conftest import client_for

GOOD = {
    "name": "Feed section",
    "elements": [
        {
            "id": "fv",
            "type": "symbol",
            "symbol": "valve.control",
            "x": 300,
            "y": 300,
            "asset_id": "fv-101",
        },
        {
            "id": "fic",
            "type": "symbol",
            "symbol": "instrument.bubble",
            "x": 300,
            "y": 200,
            "state": {"item": {"asset_id": "fic-101", "result": "linkcraft.loop_health"}},
        },
        {
            "id": "pv",
            "type": "value",
            "x": 290,
            "y": 250,
            "item": {"asset_id": "fic-101", "role": "pv"},
            "label": "PV",
        },
        {
            "id": "l1",
            "type": "line",
            "kind": "signal",
            "start": {"element": "fic"},
            "end": {"element": "fv"},
        },
    ],
}


def _draft(client, **body):
    return client.post(
        "/dash/api/diagrams/draft",
        json={"description": "The feed valve and its flow loop", "unit_id": "unit-100", **body},
    )


def test_the_model_drafts_a_diagram_from_the_units_assets(client, fake):
    fake.links.llm_answer = json.dumps(GOOD)
    answer = _draft(client)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["notes"] == []
    assert [e["id"] for e in body["diagram"]["elements"]] == ["fv", "fic", "pv", "l1"]
    DiagramPayload.model_validate(body["diagram"])
    [call] = fake.links.llm_calls
    assert call["use"] == "diagram-draft"
    assert "instrument.bubble" in call["system"]
    question = call["messages"][-1]["content"]
    assert "The feed valve and its flow loop" in question and '"fic-101"' in question
    symbols = [item["id"] for item in library()] or list(COMMON_SYMBOLS)
    assert all(symbol in question for symbol in symbols)
    # Only the unit's assets are offered.
    assert '"plant"' not in question
    # A draft: nothing saved.
    assert client.get("/dash/api/diagrams").json() == []


def test_a_draft_that_breaks_the_format_is_repaired_with_reasons(client, fake):
    broken = {
        "name": "",
        "width": 99999,
        "elements": [
            *GOOD["elements"],
            {"id": "fv", "type": "text", "text": "same id as the valve"},
            {"id": "g", "type": "gauge"},
            "not an element",
            {"id": "ghost", "type": "value", "item": {"asset_id": "zz-9", "role": "pv"}},
            {"id": "norole", "type": "value", "item": {"asset_id": "fic-101", "role": "nope"}},
            {
                "id": "p",
                "type": "symbol",
                "symbol": "pump.centrifugal",
                "running": {"item": {"asset_id": "p-201", "role": "speed"}},
                "level": {"item": {"asset_id": "p-201", "role": "flow"}, "min": 5, "max": 1},
            },
            {"id": "dangling", "type": "line", "start": {"element": "g"}, "end": {"element": "p"}},
            {"id": "BAD ID!", "type": "text", "text": "renamed"},
        ],
    }
    fake.links.llm_answer = "Here is the diagram:\n```json\n" + json.dumps(broken) + "\n```"
    body = _draft(client).json()
    diagram, notes = body["diagram"], body["notes"]
    DiagramPayload.model_validate(diagram)
    kept = {e["id"]: e for e in diagram["elements"]}
    assert diagram["name"] == "Unit 100 process display" and diagram["width"] == 8000
    assert {"fv", "fic", "pv", "l1", "p"} <= set(kept)
    assert "ghost" not in kept and "norole" not in kept and "g" not in kept
    assert "running" not in kept["p"] and "level" not in kept["p"]
    # The text with a taken id and the one with a bad id stay, renamed.
    assert [e["text"] for e in diagram["elements"] if e["type"] == "text"] == [
        "same id as the valve",
        "renamed",
    ]
    joined = " ".join(notes)
    for words in ("zz-9", "no signal role nope", "speed", "minimum", "not an object", "joins no"):
        assert words in joined, words
    # The dangling line kept its end on the pump but lost the one on the gauge: left out.
    assert "dangling" not in kept


@pytest.mark.parametrize("answer", ["Sorry, I cannot draw that.", "{not json", "[1, 2]", ""])
def test_an_answer_that_is_no_diagram_says_so(client, fake, answer):
    fake.links.llm_answer = answer
    body = _draft(client)
    assert body.status_code == 200
    assert body.json()["diagram"]["elements"] == []
    assert "held no process display" in body.json()["notes"][0]


def test_without_a_model_the_draft_says_who_sets_one_up(client, fake, runtime):
    fake.links.llm_answer = None  # off, as app.toml ships it
    answer = _draft(client)
    assert answer.status_code == 409 and "Setup" in answer.json()["detail"]


def test_without_an_app_key_the_draft_says_so(tmp_path, fake):
    from tests.conftest import make_runtime

    runtime = make_runtime(tmp_path, fake, app_key=False)
    try:
        with client_for(runtime, fake) as client:
            answer = _draft(client)
    finally:
        runtime.shutdown()
    assert answer.status_code == 409 and "app key" in answer.json()["detail"]


def test_a_model_that_cannot_answer_is_a_bad_gateway(client, runtime, monkeypatch):
    def fail(*_args, **_kwargs):
        raise PlantCraftError("upstream down", status_code=502)

    monkeypatch.setattr(runtime.suite, "ask_model", fail)
    answer = _draft(client)
    assert answer.status_code == 502 and "upstream down" in answer.json()["detail"]


def test_drafting_is_an_editors_and_checks_what_it_is_given(client, runtime, fake):
    fake.links.llm_answer = json.dumps(GOOD)
    assert _draft(client, unit_id="nowhere").status_code == 404
    assert _draft(client, description="   ").status_code == 422
    assert client.post("/dash/api/diagrams/draft", json={}).status_code == 422
    with client_for(runtime, fake, "operator") as operator:
        assert _draft(operator).status_code == 403
    assert not fake.links.llm_calls  # refused requests never reached the model


def test_without_a_unit_the_whole_plant_is_offered(client, fake):
    fake.links.llm_answer = json.dumps(GOOD)
    body = _draft(client, unit_id=None).json()
    assert body["notes"] == [] and len(body["diagram"]["elements"]) == 4
    assert "not given" in fake.links.llm_calls[0]["messages"][-1]["content"]


def test_candidates_and_answers_survive_junk():
    assets = [
        None,
        {"id": 3},
        {"id": "U", "kind": "unit"},
        {"id": "a", "parent_id": ["U"], "signals": "pv", "relations": 7},
        {
            "id": "b",
            "parent_id": "U",
            "kind": "pump",
            "signals": {"flow": "s"},
            "relations": [None, {"type": "feeds", "to": "a"}],
        },
    ]
    assert [item["id"] for item in candidates(assets, "U")] == ["b"]
    assert {item["id"] for item in candidates(assets, None)} == {"a", "b"}
    for text in ('{"elements": 5}', '{"elements": [null]}', '{"name": 4, "grid": "x"}'):
        diagram, _ = read_answer(text, known=None, symbols=set(), fallback_name="")
        DiagramPayload.model_validate(diagram)
    diagram, notes = read_answer(
        json.dumps(
            {"elements": [{"id": f"t{n}", "type": "text", "text": "x"} for n in range(700)]}
        ),
        known=None,
        symbols={"pump.centrifugal"},
        fallback_name="Big",
    )
    assert len(diagram["elements"]) == 600 and "600" in notes[0] and diagram["name"] == "Big"
    _, notes = read_answer(
        json.dumps({"elements": [{"id": "s", "type": "symbol", "symbol": "odd.one"}]}),
        known=None,
        symbols={"pump.centrifugal"},
        fallback_name="x",
    )
    assert "draws as a box" in notes[0]
