"""API v1 contributions and language model calls (docs/api-v1.md, "Language models"): an app
declares its uses of a model, Setup lists them, and the app writes with the model an
administrator gave each use."""

from __future__ import annotations

from tests.contract.test_api_v1 import ADMIN, PASSWORD, _as, _rt
from tests.contract.test_api_v1_links import _service

USES = [
    {
        "id": "algorithm-draft",
        "title": "Draft an algorithm",
        "description": "Writes a first algorithm from a description.",
        "reads": "The person's description and the blocks.",
    },
    {
        "id": "loop-summary",
        "title": "Summarize a loop",
        "description": "A paragraph on a loop's week.",
        "reads": "The loop's results.",
        "default": "off",
    },
]


class EchoModel:
    calls: list[dict] = []

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        self.label = model

    def answer(self, system, messages, tool=None, tools=None):
        EchoModel.calls.append({"system": system, "messages": messages})
        return f"Echo: {messages[-1]['content']}"


def _body(uses: list[dict]) -> dict:
    return {"app": "linkcraft", "contributes": {"llm": uses}}


def _uses(client) -> dict[str, dict]:
    client.post("/api/login", json={"username": ADMIN, "password": PASSWORD})
    body = client.get("/api/language-models").json()
    client.cookies.clear()
    return {item["use"]: item for item in body["uses"]}


def test_an_app_declares_its_uses_and_writes_with_the_model_each_was_given(central):
    headers = _service(central)
    rt = _rt(central)
    rt.specialist_chat.model_factory = EchoModel
    saved = central.put("/api/v1/contributions", json=_body(USES), headers=headers)
    assert saved.status_code == 200, saved.text
    # Setup lists them by app; "off" waits for an administrator.
    uses = _uses(central)
    draft, summary = uses["linkcraft:algorithm-draft"], uses["linkcraft:loop-summary"]
    assert draft["app"] and draft["reads"] == USES[0]["reads"]
    assert draft["choice"] == {"source": "default"} and summary["choice"] == {"source": "off"}
    ask = {"messages": [{"role": "user", "content": "Draft a filter"}], "system": "Be short."}
    url = "/api/v1/llm/algorithm-draft"
    # No model yet: 409, saying where it is set up.
    assert central.post(url, json=ask, headers=headers).status_code == 409
    store = rt.specialists
    store.save_provider(None, actor=ADMIN, name="Local", kind="openai", endpoint="http://llm:8000/v1", models=["m1", "m2"])  # fmt: skip
    store.save_settings(actor=ADMIN, provider_id="local", model="m1")
    answer = central.post(url, json=ask, headers=headers)
    assert answer.status_code == 200, answer.text
    assert answer.json()["text"] == "Echo: Draft a filter"
    assert answer.json()["use"] == "linkcraft:algorithm-draft"
    assert EchoModel.calls[-1]["system"] == "Be short."
    actions = [
        item for item in rt.workspace.audit.list() if item["action"] == "language_model.used"
    ]
    assert actions and actions[0]["username"] == "app:linkcraft"
    # The use declared off, an undeclared use and a person's token are refused.
    assert central.post(
        "/api/v1/llm/loop-summary", json=ask, headers=headers
    ).status_code == 409  # fmt: skip
    assert central.post("/api/v1/llm/nope", json=ask, headers=headers).status_code == 404
    # Named with its app too; another app's use is refused.
    named = "/api/v1/llm/linkcraft:algorithm-draft"
    assert central.post(named, json=ask, headers=headers).status_code == 200
    other = "/api/v1/llm/histcraft:algorithm-draft"
    assert central.post(other, json=ask, headers=headers).status_code == 403
    assert central.post(url, json=ask, headers=_as(central, "eng")).status_code == 403
    last_is_mine = {"messages": [{"role": "assistant", "content": "Hi"}]}
    assert central.post(url, json=last_is_mine, headers=headers).status_code == 422
    # An administrator turns the off use on with another model.
    store.save_settings(
        actor=ADMIN,
        provider_id="local",
        model="m1",
        uses={
            "linkcraft:loop-summary": {"source": "provider", "provider_id": "local", "model": "m2"}
        },
    )
    assert central.post(
        "/api/v1/llm/loop-summary", json=ask, headers=headers
    ).status_code == 200  # fmt: skip


def test_an_app_writes_with_a_model_so_many_times_a_day(central, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_LLM_APP_DAILY", "1")
    headers = _service(central)
    rt = _rt(central)
    rt.specialist_chat.model_factory = EchoModel
    central.put("/api/v1/contributions", json=_body(USES[:1]), headers=headers)
    rt.specialists.save_provider(None, actor=ADMIN, name="Local", kind="openai", endpoint="http://llm:8000/v1", models=["m1"])  # fmt: skip
    rt.specialists.save_settings(actor=ADMIN, provider_id="local", model="m1")
    ask = {"messages": [{"role": "user", "content": "x"}]}
    assert central.post("/api/v1/llm/algorithm-draft", json=ask, headers=headers).status_code == 200
    assert central.post("/api/v1/llm/algorithm-draft", json=ask, headers=headers).status_code == 429


def _ready(rt) -> None:
    rt.specialist_chat.model_factory = EchoModel
    rt.specialists.save_provider(None, actor=ADMIN, name="Local", kind="openai", endpoint="http://llm:8000/v1", models=["m1"])  # fmt: skip
    rt.specialists.save_settings(actor=ADMIN, provider_id="local", model="m1")


def test_writing_with_a_model_needs_write_llm_in_the_apps_permissions(central):
    """Security audit 2026-10-26: text leaves the plant only where the administrator saw it."""

    headers = _service(central)
    rt = _rt(central)
    _ready(rt)
    ask = {"messages": [{"role": "user", "content": "x"}]}
    body = {**_body(USES[:1]), "version": "9.0.0", "permissions": ["write.audit"]}
    central.put("/api/v1/contributions", json=body, headers=headers)
    rt.app_scopes.forget()
    refused = central.post("/api/v1/llm/algorithm-draft", json=ask, headers=headers)
    assert refused.status_code == 403 and "write.llm" in refused.json()["detail"]
    body["permissions"] = ["write.audit", "write.llm"]
    central.put("/api/v1/contributions", json=body, headers=headers)
    rt.app_scopes.forget()
    assert central.post("/api/v1/llm/algorithm-draft", json=ask, headers=headers).status_code == 200


def test_a_use_of_an_app_outside_the_suite_starts_off(central, monkeypatch):
    headers = _service(central)
    rt = _rt(central)
    _ready(rt)
    central.put("/api/v1/contributions", json=_body(USES[:1]), headers=headers)
    monkeypatch.setenv("PLANTCRAFT_APPS", "dashcraft=/dash/")
    ask = {"messages": [{"role": "user", "content": "x"}]}
    assert central.post("/api/v1/llm/algorithm-draft", json=ask, headers=headers).status_code == 409
    rt.specialists.save_settings(
        actor=ADMIN,
        provider_id="local",
        model="m1",
        uses={"linkcraft:algorithm-draft": {"source": "default"}},
    )
    assert central.post("/api/v1/llm/algorithm-draft", json=ask, headers=headers).status_code == 200
