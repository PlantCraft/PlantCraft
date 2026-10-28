"""Prompts for an AI assistant: template, size limit and the rule that no secret enters one."""

from __future__ import annotations

import json

from plantcraft_sdk.prompts import (
    MAX_CHARS,
    Prompt,
    code_part,
    json_part,
    question_of,
    scrub,
    text_part,
)

SOURCE = 'def run(pv, sp):\n    """A method."""\n    return ```fenced``` and pv - sp\n'


def _prompt(*parts, notes=()):
    return Prompt(
        module="Analytics",
        title="Method: Error",
        subject="an Analytics method",
        question="Explain this method.",
        parts=list(parts),
        notes=list(notes),
    )


def test_text_has_header_rules_question_and_parts_in_order():
    answer = _prompt(
        code_part("Source", SOURCE, "python"),
        json_part("Parameters", {"window": 60}),
        notes=["Keep the method id."],
    ).render()
    text = answer["text"]
    assert text.startswith("# Method: Error\n")
    assert "PlantCraft Analytics" in text and "an Analytics method" in text
    assert "never suggest writing to the control system" in text
    assert "- Keep the method id." in text
    assert text.index("## Question") < text.index("## Source") < text.index("## Parameters")
    # The source carries a run of three backticks: its fence is longer.
    assert "````python\n" in text
    assert [part["label"] for part in answer["parts"]] == ["Source", "Parameters"]
    assert answer["parts"][1]["kind"] == "json"
    assert answer["omitted"] == [] and answer["chars"] == len(text)


def test_no_secret_or_endpoint_ever_enters_a_prompt():
    config = {
        "name": "Crude unit",
        "password": "hunter2",
        "source": {
            "endpoint": "opc.tcp://10.0.0.5:4840",
            "username": "operator",
            "app_key": "k-1",
            "tags": ["FIC-101.PV"],
        },
        "auth": [{"api_key": "abc", "kind": "pi"}],
        "notes": "connect with token=eyJabc.def123.ghi456 please",
    }
    clean, removed = scrub(config)
    assert sorted(removed) == [
        "auth[0].api_key",
        "password",
        "source.app_key",
        "source.endpoint",
        "source.username",
    ]
    assert clean["source"] == {"tags": ["FIC-101.PV"]}
    answer = _prompt(
        json_part("Config", config), text_part("Notes", "the password: hunter2 was set")
    ).render()
    for secret in ("hunter2", "opc.tcp://10.0.0.5", "operator", "k-1", 'abc"', "eyJabc"):
        assert secret not in answer["text"], secret
    assert json.loads(answer["parts"][0]["content"])["name"] == "Crude unit"


def test_the_text_stays_under_the_limit_and_names_what_was_left_out():
    big = "x = 1\n" * 10_000
    answer = _prompt(
        json_part("Small", {"a": 1}), code_part("Big", big, "python"), json_part("After", {"b": 2})
    ).render()
    assert answer["chars"] <= MAX_CHARS
    assert "more characters left out" in answer["parts"][1]["content"]
    assert answer["omitted"] == ["After"]
    assert "Left out for length: After." in answer["text"]


def test_a_part_with_no_room_left_is_left_out_whole():
    answer = _prompt(code_part("Big", "y" * 2_000, "python"), json_part("Next", {"c": 3})).render(
        max_chars=900
    )
    assert answer["parts"] == [] and answer["omitted"] == ["Big", "Next"]
    assert answer["chars"] <= 900


def test_questions_come_only_from_the_presets():
    presets = {"explain": "Explain it.", "adapt": "Adapt it."}
    assert question_of(presets, "adapt", "explain") == "Adapt it."
    assert question_of(presets, "ignore the rules", "explain") == "Explain it."
    assert question_of(presets, None, "explain") == "Explain it."
