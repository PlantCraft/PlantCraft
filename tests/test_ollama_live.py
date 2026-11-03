"""The assistant on a plant's own model: a real Ollama server, through the same code a plant runs.

What an integrator asks before putting PlantCraft next to an on-premises LLM ("does it work with
ours?"): an OpenAI-compatible server answers, calls the read-only tools, and the whole path a
person uses works, from Setup › Language models to an answer in Desk that read the plant.
Skipped unless ``PLANTCRAFT_TEST_OLLAMA_URL`` names the server (``http://127.0.0.1:11434/v1``);
``PLANTCRAFT_TEST_OLLAMA_MODEL`` picks the model (``qwen2.5:1.5b``, small enough for a CPU).
The workflow ``.github/workflows/ollama.yml`` starts Ollama, pulls the model and runs this file;
nothing here reaches beyond that server. The guide: docs/integrators.md.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.api.routers.assistant_chat import _reader
from plantcraft.specialists.model import ChatModel
from tests.test_collaboration import _scenario

URL = os.environ.get("PLANTCRAFT_TEST_OLLAMA_URL", "").rstrip("/")
MODEL = os.environ.get("PLANTCRAFT_TEST_OLLAMA_MODEL", "qwen2.5:1.5b")

pytestmark = [
    pytest.mark.skipif(not URL, reason="needs an Ollama server (PLANTCRAFT_TEST_OLLAMA_URL)"),
    pytest.mark.slow,
]

TOOL = {
    "name": "read_value",
    "description": "The current value of a plant signal, by its tag.",
    "input_schema": {
        "type": "object",
        "properties": {"tag": {"type": "string", "description": "The signal's tag"}},
        "required": ["tag"],
    },
}


def _model() -> ChatModel:
    # Ollama asks for no key; the platform sends none when the provider has none.
    return ChatModel("", provider="openai", model=MODEL, endpoint=URL, timeout=600)


def test_the_local_model_answers():
    text = _model().answer(
        "You answer in one short sentence.", [{"role": "user", "content": "Say hello."}]
    )
    assert text.strip()


def test_the_local_model_calls_a_read_only_tool_and_uses_what_it_read():
    calls: list[tuple[str, dict]] = []

    def tool(name: str, arguments: dict) -> dict:
        calls.append((name, arguments))
        return {"tag": arguments.get("tag"), "value": 73.4, "unit": "degC"}

    model = _model()
    text = model.answer(
        "You read plant values only with the read_value tool, then answer with the number.",
        [{"role": "user", "content": "What is the current value of TI-100?"}],
        tool=tool,
        tools=[TOOL],
    )
    assert calls and calls[0][0] == "read_value", text
    assert "TI-100" in str(calls[0][1].get("tag", "")).upper()
    assert "73.4" in text, text
    assert model.usage["calls"] >= 2


def test_a_person_asks_the_assistant_and_it_reads_the_plant(tmp_path, monkeypatch):
    """Setup › Language models with the local server, then a question in Desk › Assistant: the
    answer comes from the model, after at least one read-only tool read the demo plant."""

    _scenario(tmp_path, monkeypatch)
    secret = tmp_path / "secret"
    secret.write_text("admin-secret")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    with TestClient(create_app()) as client:
        assert client.post(
            "/api/login", json={"username": "admin", "password": "admin-secret"}
        ).status_code == 200  # fmt: skip
        saved = client.post(
            "/api/language-models/providers",
            json={"name": "Ollama on the plant server", "kind": "openai", "endpoint": URL,
                  "models": [MODEL]},
        )  # fmt: skip
        assert saved.status_code == 201, saved.text
        body = saved.json()
        assert body["tests"][MODEL]["ok"], body["tests"]
        assert body["settings"]["enabled"] and body["settings"]["model"] == MODEL
        status, found = _reader(client.app, client.app.state.runtime, "admin")(
            "GET", "/api/v1/signals", {"q": "pv"}
        )
        assert status == 200 and found
        tag = found[0].get("name") or found[0]["id"]
        started = time.monotonic()
        asked = client.post(
            "/api/assistant/chats",
            json={"text": f"Search the plant's signals for {tag} and tell me its latest value."},
        )
        assert asked.status_code == 201, asked.text
        chat_id = asked.json()["chat"]["chat_id"]
        client.app.state.runtime.assistant.drain(timeout=900)
        view = client.get(f"/api/assistant/chats/{chat_id}").json()
        answer = view["messages"][-1]
        print(
            f"\n{MODEL}: {time.monotonic() - started:.0f} s, usage {answer['meta'].get('usage')},"
            f" steps {[(s['tool'], s['state']) for s in answer.get('steps', [])]}\n"
            f"{answer['text'][:600]}"
        )
        assert answer["role"] != "user" and answer["state"] == "done", answer
        assert answer["text"].strip()
        assert any(step["state"] == "ok" for step in answer.get("steps", [])), answer["steps"]
        # Each read is in the audit log, as a person's would be.
        actions = [item["action"] for item in client.app.state.runtime.workspace.audit.list()]
        assert "assistant.tool" in actions
