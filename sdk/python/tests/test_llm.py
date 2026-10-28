"""An app writes with a language model through PlantCraft: ``client.llm`` against the uses its
``[[contributes.llm]]`` declares (plantcraft_sdk.llm)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plantcraft_sdk.client import BadRequest, Forbidden, NotFound
from plantcraft_sdk.llm import messages_body, split_use
from plantcraft_sdk.testing import FakePlantCraft

USES = [
    {"id": "algorithm-draft", "title": "Draft an algorithm", "reads": "The description."},
    {"id": "loop-summary", "title": "Summarize a loop", "default": "off"},
]


@pytest.fixture
def fake():
    return FakePlantCraft(now=datetime(2026, 10, 25, 12, tzinfo=timezone.utc))


def _service(fake):
    return fake.client(None, app="linkcraft", key="test-app-key")


def test_messages_are_a_question_or_the_turns_of_a_chat():
    assert messages_body("Why?") == {
        "system": "",
        "messages": [{"role": "user", "content": "Why?"}],
    }
    with pytest.raises(ValueError):
        messages_body([{"role": "system", "content": "x"}])
    with pytest.raises(ValueError):
        messages_body([{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}])
    assert split_use("linkcraft", "linkcraft:draft") == "draft" == split_use("linkcraft", "draft")
    with pytest.raises(ValueError):
        split_use("linkcraft", "histcraft:draft")


def test_an_app_writes_with_the_uses_it_declared(fake):
    client = _service(fake)
    client.put_contributions({"contributes": {"llm": USES}})
    answer = client.llm("algorithm-draft", "Draft a filter", system="Be short.")
    assert answer == {
        "use": "linkcraft:algorithm-draft",
        "model": "fake",
        "text": "A model's answer.",
    }
    assert fake.links.llm_calls[-1]["system"] == "Be short."
    assert client.llm("linkcraft:algorithm-draft", "x")["use"] == "linkcraft:algorithm-draft"
    with pytest.raises(NotFound):
        client.llm("nope", "x")
    with pytest.raises(Forbidden):
        client.llm("histcraft:algorithm-draft", "x")
    with pytest.raises(Forbidden):
        fake.client("engineer").llm("algorithm-draft", "x")
    # No model for the use now: 409, which the app says to the person.
    fake.links.llm_answer = None
    with pytest.raises(BadRequest) as refused:
        client.llm("algorithm-draft", "x")
    assert refused.value.status_code == 409
    fake.links.llm_answer = lambda call: call["messages"][-1]["content"].upper()
    assert client.llm("algorithm-draft", "ok")["text"] == "OK"
