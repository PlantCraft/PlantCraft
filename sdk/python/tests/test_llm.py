"""An app writes with a language model through PlantCraft: ``client.llm`` against the uses its
``[[contributes.llm]]`` declares (plantcraft_sdk.llm)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plantcraft_sdk.client import BadRequest, Forbidden, NotFound
from plantcraft_sdk.llm import MAX_IMAGE_BYTES, image, messages_body, split_use
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


PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_a_user_turn_carries_images_for_a_model_that_reads_them():
    body = messages_body("What is drawn?", images=[PNG])
    turn = body["messages"][-1]
    assert turn["content"] == "What is drawn?" and len(turn["images"]) == 1
    assert turn["images"][0] == image(PNG)
    jpeg = image(b"\xff\xd8\xff" + b"\0" * 8, "image/jpeg")
    chat = [{"role": "user", "content": "Read this", "images": [jpeg]}]
    assert messages_body(chat)["messages"][0]["images"] == [jpeg]
    with pytest.raises(ValueError, match="one of"):
        messages_body("x", images=[{"media_type": "application/pdf", "data": "AAAA"}])
    with pytest.raises(ValueError, match="base64"):
        messages_body("x", images=[{"media_type": "image/png", "data": "not base64!"}])
    with pytest.raises(ValueError, match="at most 4"):
        messages_body("x", images=[PNG] * 5)
    with pytest.raises(ValueError, match="MB"):
        messages_body("x", images=[b"\0" * (MAX_IMAGE_BYTES + 1)])
    with pytest.raises(ValueError, match="user's turn"):
        messages_body([{"role": "assistant", "content": "y", "images": [PNG]}, {"content": "z"}])


def test_the_fake_receives_the_images(fake):
    client = _service(fake)
    client.put_contributions({"contributes": {"llm": USES}})
    fake.links.llm_answer = lambda call: f"{len(call['messages'][-1].get('images', []))} image"
    assert client.llm("algorithm-draft", "What is drawn?", images=[PNG])["text"] == "1 image"
