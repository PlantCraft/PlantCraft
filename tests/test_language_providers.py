# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""Setup › Language models: several providers, each with its models, and each specialist
answering with the provider and model it was given (owner, 2026-10-22)."""

from __future__ import annotations

import json

from tests.test_collaboration import FakeModel, _specialist, _talk, signed  # noqa: F401

LOCAL = {
    "name": "Ollama on the plant server",
    "kind": "openai",
    "endpoint": "http://llm.plant.local:11434/v1",
    "models": ["llama3.1:70b", "qwen2.5:32b", "llama3.1:70b", " "],
}
HOSTED = {"name": "Claude", "kind": "anthropic", "models": ["claude-sonnet-5-5"]}


class EchoModel(FakeModel):
    def answer(self, system, messages, tool=None, tools=None):
        return "It works."


class DownModel(FakeModel):
    """A model that does not answer (wrong address or key)."""

    def answer(self, system, messages, tool=None, tools=None):
        raise RuntimeError("Connection refused")


def test_providers_are_listed_with_their_models_and_keys_never_come_back(signed):
    signed.app.state.runtime.specialist_chat.model_factory = DownModel
    empty = signed.get("/api/language-models").json()
    assert empty["providers"] == [] and empty["settings"]["enabled"] is False
    assert [item["use"] for item in empty["uses"]] == ["assistant", "plant-draft"]
    first = signed.post("/api/language-models/providers", json=LOCAL)
    assert first.status_code == 201, first.text
    body = first.json()
    local = body["providers"][0]
    assert local["provider_id"] == "ollama-on-the-plant-server" and local["ready"] is True
    assert local["models"] == ["llama3.1:70b", "qwen2.5:32b"]
    # Each model is tested on save; none answered, so there is no default and models stay off.
    assert set(body["tests"]) == {"llama3.1:70b", "qwen2.5:32b"}
    assert not any(test["ok"] for test in body["tests"].values())
    assert body["settings"]["provider_id"] == "" and body["settings"]["enabled"] is False
    hosted = signed.post(
        "/api/language-models/providers", json={**HOSTED, "api_key": "sk-ant-secret-wxyz"}
    ).json()
    assert "sk-ant-secret" not in json.dumps(hosted)
    claude = next(item for item in hosted["providers"] if item["kind"] == "anthropic")
    assert claude["api_key_hint"] == "…wxyz" and claude["ready"] is True
    # Without a key, a hosted API is not ready; a None key keeps the saved one.
    kept = signed.put(f"/api/language-models/providers/{claude['provider_id']}", json=HOSTED).json()
    assert next(item for item in kept["providers"] if item["kind"] == "anthropic")["api_key_set"]
    bad = signed.post("/api/language-models/providers", json={**LOCAL, "models": []})
    assert bad.status_code == 422
    assert signed.put(
        "/api/language-models/providers/nope", json=LOCAL
    ).status_code == 404  # fmt: skip
    assert signed.post(
        "/api/language-models/providers", json={**LOCAL, "endpoint": "ftp://x"}
    ).status_code == 422  # fmt: skip
    # The default must be one of the provider's models; choosing it turns models on.
    settings = {"provider_id": claude["provider_id"], "model": "gpt-4o"}
    assert signed.put("/api/language-models/settings", json=settings).status_code == 422
    settings["model"] = "claude-sonnet-5-5"
    saved = signed.put("/api/language-models/settings", json=settings).json()
    assert saved["settings"]["enabled"] and saved["settings"]["provider_id"] == "claude"
    # The old single connection reads the default.
    connection = signed.get("/api/language-model").json()
    assert connection["provider"] == "anthropic" and connection["name"] == "claude-sonnet-5-5"
    # No default: off again.
    off = signed.put("/api/language-models/settings", json={"provider_id": "", "model": ""})
    assert off.json()["settings"]["enabled"] is False
    actions = {item["action"] for item in signed.app.state.runtime.workspace.audit.list()}
    assert {"language_model.provider_added", "language_model.changed"} <= actions


def test_the_first_model_that_answers_becomes_the_default(signed):
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = EchoModel
    body = signed.post("/api/language-models/providers", json=LOCAL).json()
    assert (
        body["tests"]["llama3.1:70b"]["ok"] and body["tests"]["llama3.1:70b"]["text"] == "It works."
    )
    assert body["settings"]["enabled"] is True
    assert body["settings"]["model"] == "llama3.1:70b"
    assert rt.assistant.status()["available"] is True
    # A second provider that answers does not take the default.
    signed.post("/api/language-models/providers", json={**HOSTED, "api_key": "sk-ant-x-1234"})
    assert signed.get("/api/language-models").json()["settings"]["model"] == "llama3.1:70b"


def test_a_tested_model_becomes_the_default_when_there_is_none(signed):
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = DownModel
    signed.post("/api/language-models/providers", json=LOCAL)
    assert rt.assistant.status()["available"] is False
    rt.specialist_chat.model_factory = EchoModel
    url = "/api/language-models/providers/ollama-on-the-plant-server/test"
    assert signed.post(url, json={"model": "qwen2.5:32b"}).json()["ok"] is True
    settings = signed.get("/api/language-models").json()["settings"]
    assert settings["enabled"] and settings["model"] == "qwen2.5:32b"


def test_each_use_writes_with_the_default_another_model_or_nothing(signed):
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = EchoModel
    signed.post("/api/language-models/providers", json=LOCAL)
    use = {"source": "provider", "provider_id": "ollama-on-the-plant-server"}
    payload = {"provider_id": "ollama-on-the-plant-server", "model": "llama3.1:70b"}
    wrong = {**payload, "uses": {"assistant": {**use, "model": "gpt-4o"}}}
    assert signed.put("/api/language-models/settings", json=wrong).status_code == 422
    unknown = {**payload, "uses": {"nope": {"source": "off"}}}
    assert signed.put("/api/language-models/settings", json=unknown).status_code == 422
    own = {**payload, "uses": {"assistant": {**use, "model": "qwen2.5:32b"}}}
    body = signed.put("/api/language-models/settings", json=own).json()
    assert body["uses"][0]["choice"]["model"] == "qwen2.5:32b" and body["uses"][0]["ready"]
    assert rt.specialists.use_model("assistant")["name"] == "qwen2.5:32b"
    off = {**payload, "uses": {"assistant": {"source": "off"}}}
    body = signed.put("/api/language-models/settings", json=off).json()
    assert body["uses"][0]["ready"] is False and rt.assistant.status()["available"] is False
    # Removing the provider sends its uses back to the default (none now: models off).
    signed.put("/api/language-models/settings", json=own)
    signed.delete("/api/language-models/providers/ollama-on-the-plant-server")
    settings = signed.get("/api/language-models").json()["settings"]
    assert settings["uses"] == {} and settings["enabled"] is False


def test_each_specialist_answers_with_its_provider_and_model(signed):
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = FakeModel
    FakeModel.calls = []
    signed.post("/api/language-models/providers", json=LOCAL)
    _specialist(signed)
    profile = {"display_name": "Malhas", "apps": ["linkcraft"]}
    wrong = {"source": "provider", "provider_id": "ollama-on-the-plant-server", "name": "gpt-4o"}
    assert signed.put(
        "/api/specialists/malhas", json={**profile, "model": wrong}
    ).status_code == 422  # fmt: skip
    model = {**wrong, "name": "qwen2.5:32b"}
    saved = signed.put("/api/specialists/malhas", json={**profile, "model": model}).json()
    assert saved["model"]["source"] == "provider" and saved["model"]["ready"] is True
    _talk(signed, "olá")
    assert FakeModel.calls[-1] == {
        "key": "", "model": "qwen2.5:32b", "endpoint": LOCAL["endpoint"],
    }  # fmt: skip
    used = signed.get("/api/language-models").json()["providers"][0]["used_by"]
    assert used == ["Malhas"]
    # Removing the provider says who used it; the specialist is then not ready.
    removed = signed.delete("/api/language-models/providers/ollama-on-the-plant-server").json()
    assert removed["orphans"] == ["malhas"] and removed["settings"]["provider_id"] == ""
    assert signed.get("/api/specialists").json()["items"][0]["model"]["ready"] is False


def test_each_model_of_a_provider_can_be_tested(signed):
    signed.app.state.runtime.specialist_chat.model_factory = EchoModel
    signed.post("/api/language-models/providers", json=LOCAL)
    url = "/api/language-models/providers/ollama-on-the-plant-server/test"
    answer = signed.post(url, json={"model": "qwen2.5:32b"}).json()
    assert answer["ok"] is True and answer["text"] == "It works."
    assert signed.post("/api/language-models/providers/nope/test", json={}).status_code == 404


def test_the_single_connection_of_before_becomes_a_provider(tmp_path):
    from processcraft.auth.users import UserStore
    from processcraft.db import Database
    from processcraft.specialists.profiles import (
        INSTALLATION_KEY,
        KeyFile,
        SpecialistStore,
    )

    db = Database(tmp_path / "w.db")
    users = UserStore(db)
    keys = KeyFile(tmp_path / "keys.json")
    store = SpecialistStore(db, users, keys)
    # As an installation from before this round had saved it.
    store._write_settings(
        {
            "enabled": True,
            "provider": "openai",
            "name": "llama3.1:70b",
            "endpoint": "http://llm.plant.local:11434/v1",
        },
        "admin",
    )
    keys.set(INSTALLATION_KEY, "sk-local-abcd")
    adopted = SpecialistStore(db, users, keys)
    assert [item["provider_id"] for item in adopted.providers()] == ["default"]
    assert adopted.provider_key("default") == "sk-local-abcd"
    connection = adopted.connection()
    assert connection["enabled"] and connection["name"] == "llama3.1:70b" and connection["ready"]


def test_a_switch_left_off_before_leaves_no_default(tmp_path):
    from processcraft.auth.users import UserStore
    from processcraft.db import Database
    from processcraft.specialists.profiles import KeyFile, SpecialistStore

    db = Database(tmp_path / "w.db")
    users = UserStore(db)
    keys = KeyFile(tmp_path / "keys.json")
    store = SpecialistStore(db, users, keys)
    store.save_provider(None, actor="admin", name="OpenAI", kind="openai", models=["gpt-5"])
    # As 0.4.0 saved it: a default chosen, the switch beside it off.
    store._write_settings(
        {"version": 2, "enabled": False, "provider_id": "openai", "model": "gpt-5"}, "admin"
    )
    settings = SpecialistStore(db, users, keys).settings()
    assert settings["enabled"] is False and settings["provider_id"] == ""
    store._write_settings(
        {"version": 2, "enabled": True, "provider_id": "openai", "model": "gpt-5"}, "admin"
    )
    settings = SpecialistStore(db, users, keys).settings()
    assert settings["enabled"] is True and settings["model"] == "gpt-5"
