# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""The installation's language model (``/api/language-model``): the one connection, usually
the company's own or a local model, every specialist answers with unless it has its own; and
the OpenAI chat completions format most of those models speak."""

from __future__ import annotations

import io
import json

from plantcraft.specialists import model as model_module
from plantcraft.specialists.model import ChatModel
from tests.test_collaboration import (  # noqa: F401
    FakeModel,
    _asset_id,
    _publish_result,
    _specialist,
    _talk,
    signed,
)

LOCAL = {
    "enabled": True,
    "provider": "openai",
    "name": "llama3.1:70b",
    "endpoint": "http://llm.plant.local:11434/v1",
}


def test_the_connection_is_set_once_and_its_key_never_comes_back(signed):
    empty = signed.get("/api/language-model").json()
    assert empty["enabled"] is False and empty["ready"] is False
    assert {item["id"] for item in empty["providers"]} == {"anthropic", "openai"}
    saved = signed.put("/api/language-model", json={**LOCAL, "api_key": "sk-local-abcd"}).json()
    assert saved["ready"] is True and saved["api_key_hint"] == "…abcd"
    assert "sk-local" not in json.dumps(saved)
    kept = signed.put("/api/language-model", json=LOCAL).json()  # no key: the saved one stays
    assert kept["api_key_set"] is True
    # A local model needs no key; a name it does.
    assert signed.put("/api/language-model", json={**LOCAL, "api_key": ""}).json()["ready"] is True
    assert signed.put("/api/language-model", json={**LOCAL, "name": ""}).status_code == 422
    bad = {**LOCAL, "endpoint": "ftp://x"}
    assert signed.put("/api/language-model", json=bad).status_code == 422
    entries = signed.app.state.runtime.workspace.audit.list()
    assert any(item["action"] == "language_model.changed" for item in entries)


def test_specialists_answer_with_the_installations_model(signed):
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = FakeModel
    FakeModel.calls = []
    created = _specialist(signed)
    assert created["model"]["source"] == "installation" and created["model"]["ready"] is False
    signed.put("/api/language-model", json={**LOCAL, "api_key": "sk-local-abcd"})
    assert signed.get("/api/specialists").json()["items"][0]["model"]["ready"] is True
    asset = _asset_id(signed)
    _publish_result(signed, f"asset:{asset}")
    FakeModel.ref = f"asset:{asset}"
    _id, messages = _talk(signed, f"#asset:{asset}")
    assert messages[-1]["text"] == "Model saw 1 result(s)."
    assert FakeModel.calls[-1] == {
        "key": "sk-local-abcd", "model": "llama3.1:70b", "endpoint": LOCAL["endpoint"],
    }  # fmt: skip
    # Turned off in the profile, the script answers.
    signed.put(
        "/api/specialists/malhas",
        json={"display_name": "Malhas", "apps": ["linkcraft"], "model": {"source": "off"}},
    )
    _id, messages = _talk(signed, "olá")
    assert messages[-1]["meta"]["writer"] == "script"


class EchoModel(FakeModel):
    def answer(self, system, messages, tool=None, tools=None):
        return "It works."


def test_the_test_button_reaches_the_installations_model(signed, monkeypatch):
    signed.app.state.runtime.specialist_chat.model_factory = EchoModel
    assert signed.post("/api/language-model/test").json()["ok"] is False  # not set up
    signed.put("/api/language-model", json=LOCAL)
    answer = signed.post("/api/language-model/test").json()
    assert answer == {"ok": True, "writer": "Claude · llama3.1:70b", "text": "It works."}
    monkeypatch.setenv("PLANTCRAFT_LLM", "off")
    assert signed.post("/api/language-model/test").json()["ok"] is False


def test_an_app_is_a_subject_the_assistant_talks_about(signed):
    _specialist(signed)
    body = signed.get("/api/v1/assistant", params={"ref": "app:linkcraft"}).json()
    assert body["suggested"] == ["malhas"]
    assert body["ref"]["kind"] == "app" and body["ref"]["exists"] is True


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_the_openai_format_carries_tools_both_ways(monkeypatch):
    sent: list[dict] = []
    answers = [
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "list_attention",
                                    "arguments": '{"limit": 3}',
                                },
                            }
                        ],
                    },
                }
            ]
        },
        {"choices": [{"finish_reason": "stop", "message": {"content": "FIC-101 is worst."}}]},
    ]

    def urlopen(request, timeout):
        sent.append(
            {
                "url": request.full_url,
                "headers": dict(request.headers),
                "body": json.loads(request.data),
            }
        )
        return _Response(json.dumps(answers.pop(0)).encode())

    monkeypatch.setattr(
        model_module, "_open", lambda request, timeout, proxy="": urlopen(request, timeout)
    )
    model = ChatModel("sk-x", provider="openai", model="qwen2.5", endpoint=LOCAL["endpoint"])
    calls = []
    tools = [
        {
            "name": "list_attention",
            "description": "Worst first.",
            "input_schema": {"type": "object"},
        }
    ]
    text = model.answer(
        "Be brief.",
        [{"role": "user", "content": "Which loops are worst?"}],
        tool=lambda name, args: calls.append((name, args)) or [{"ref": "asset:FIC-101"}],
        tools=tools,
    )
    assert text == "FIC-101 is worst." and calls == [("list_attention", {"limit": 3})]
    assert sent[0]["url"] == "http://llm.plant.local:11434/v1/chat/completions"
    assert sent[0]["headers"]["Authorization"] == "Bearer sk-x"
    first = sent[0]["body"]
    assert first["model"] == "qwen2.5" and first["messages"][0] == {
        "role": "system",
        "content": "Be brief.",
    }
    assert first["tools"][0]["function"]["name"] == "list_attention"
    second = sent[1]["body"]["messages"]
    assert second[2]["tool_calls"][0]["id"] == "call_1"
    assert second[3]["role"] == "tool" and second[3]["tool_call_id"] == "call_1"


def test_the_answers_length_goes_in_the_form_the_service_takes(monkeypatch):
    """OpenAI's newer models refuse max_tokens ("Use 'max_completion_tokens'
    instead"); servers that speak the older form take max_tokens. The client starts from the
    form its address suggests and switches once when the service names the other."""

    import urllib.error

    sent: list[dict] = []
    refuse: set[str] = set()

    def urlopen(request, timeout):
        body = json.loads(request.data)
        sent.append(body)
        wrong = next((key for key in refuse if key in body), None)
        if wrong:
            detail = json.dumps({"error": {"message": f"Unsupported parameter: '{wrong}' is not supported with this model.", "param": wrong}})  # fmt: skip
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(detail.encode()))  # fmt: skip
        return _Response(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}).encode())  # fmt: skip

    monkeypatch.setattr(
        model_module, "_open", lambda request, timeout, proxy="": urlopen(request, timeout)
    )
    ask = [{"role": "user", "content": "hi"}]
    # An OpenAI-compatible server on the plant's network: the older form at once.
    local = ChatModel("", provider="openai", model="qwen2.5", endpoint=LOCAL["endpoint"])
    assert local.answer("Be brief.", ask) == "ok"
    assert sent[-1]["max_tokens"] == model_module.MAX_TOKENS
    # A gateway in front of OpenAI that refuses max_tokens: switch once, and keep the new form.
    refuse.add("max_tokens")
    sent.clear()
    gateway = ChatModel("sk-x", provider="openai", model="gpt-6-luna", endpoint=LOCAL["endpoint"])
    assert gateway.answer("Be brief.", ask) == "ok"
    assert ["max_tokens" in body for body in sent] == [True, False]
    assert gateway.token_param == "max_completion_tokens"
    gateway.answer("Be brief.", ask)
    assert len(sent) == 3 and "max_completion_tokens" in sent[-1]
    # Both refused: the service's own words reach the administrator.
    refuse.add("max_completion_tokens")
    try:
        gateway.answer("Be brief.", ask)
        raise AssertionError("expected an error")
    except RuntimeError as exc:
        assert "400" in str(exc) and "Unsupported parameter" in str(exc)


def test_openai_itself_is_asked_through_responses_with_tools_and_reasoning(monkeypatch):
    """a work on Today answered 400 "function tools with reasoning effort
    are not supported" (gpt-6-luna in chat completions). OpenAI's own service is asked through
    its Responses API, which takes tools with reasoning; the effort is the provider's."""

    sent: list[dict] = []
    answers = [
        {
            "status": "completed",
            "output": [
                {"type": "reasoning", "id": "rs_1", "summary": []},
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "list_attention",
                    "arguments": '{"limit": 3}',
                },  # fmt: skip
            ],
        },
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "FIC-101 is worst."}],
                }  # fmt: skip
            ],
        },
    ]

    def urlopen(request, timeout):
        sent.append({"url": request.full_url, "body": json.loads(request.data)})
        return _Response(json.dumps(answers.pop(0)).encode())

    monkeypatch.setattr(
        model_module, "_open", lambda request, timeout, proxy="": urlopen(request, timeout)
    )
    model = ChatModel("sk-x", provider="openai", model="gpt-6-luna", reasoning="low")
    tools = [{"name": "list_attention", "description": "Worst first.", "input_schema": {"type": "object"}}]  # fmt: skip
    calls = []
    text = model.answer(
        "Be brief.",
        [{"role": "user", "content": "Which loops are worst?"}],
        tool=lambda name, args: calls.append((name, args)) or [{"ref": "asset:FIC-101"}],
        tools=tools,
    )
    assert text == "FIC-101 is worst." and calls == [("list_attention", {"limit": 3})]
    first, second = sent[0]["body"], sent[1]["body"]
    assert sent[0]["url"] == "https://api.openai.com/v1/responses"
    assert first["instructions"] == "Be brief." and first["store"] is False
    assert first["reasoning"] == {"effort": "low"} and "max_output_tokens" in first
    assert first["tools"][0] == {"type": "function", "name": "list_attention", "description": "Worst first.", "parameters": {"type": "object"}, "strict": False}  # fmt: skip
    assert second["input"][1] == {"type": "function_call", "call_id": "call_1", "name": "list_attention", "arguments": '{"limit": 3}'}  # fmt: skip
    assert second["input"][2]["type"] == "function_call_output"
    assert second["input"][2]["call_id"] == "call_1"
    # No effort set: the service's own (a model that does not reason refuses the parameter).
    answers.append({"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]})  # fmt: skip
    plain = ChatModel("sk-x", provider="openai", model="gpt-5-nano")
    assert plain.answer("Be brief.", [{"role": "user", "content": "hi"}]) == "ok"
    assert "reasoning" not in sent[-1]["body"]
    # A server of the plant's network with an effort: chat completions' reasoning_effort.
    answers.append({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})
    local = ChatModel("", provider="openai", model="qwen3", endpoint=LOCAL["endpoint"], reasoning="high")  # fmt: skip
    assert local.answer("Be brief.", [{"role": "user", "content": "hi"}]) == "ok"
    assert sent[-1]["body"]["reasoning_effort"] == "high"


def test_a_provider_keeps_its_reasoning_effort_and_its_test_offers_a_tool(signed):
    seen: list[dict] = []

    class Probe(FakeModel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen.append({**kwargs})

        def answer(self, system, messages, tool=None, tools=None):
            seen[-1]["tools"] = [item["name"] for item in tools or []]
            return "It works."

    signed.app.state.runtime.specialist_chat.model_factory = Probe
    draft = {"name": "OpenAI", "kind": "openai", "models": ["gpt-6-luna"], "api_key": "sk-test-abcd", "reasoning": "low"}  # fmt: skip
    saved = signed.post("/api/language-models/providers", json=draft).json()
    provider = next(item for item in saved["providers"] if item["name"] == "OpenAI")
    assert provider["reasoning"] == "low"
    assert seen[-1]["reasoning"] == "low" and seen[-1]["tools"] == ["plant_clock"]
    wrong = signed.put(f"/api/language-models/providers/{provider['provider_id']}", json={**draft, "reasoning": "max"})  # fmt: skip
    assert wrong.status_code == 422


def test_the_assistant_of_an_app_reads_what_the_app_says_about_itself(signed):
    from tests.test_assistant import _service

    _specialist(signed)
    overview = {
        "ref": "app:linkcraft",
        "kind": "overview",
        "title": "Link: everything it judged",
        "text": "Worst first: loop FIC-101 alarm, health 31.",
        "url": "/link/results",
    }
    saved = signed.put("/api/v1/knowledge", json=[overview], headers=_service(signed)).json()
    assert saved["saved"] == 1, saved
    rt = signed.app.state.runtime
    facts = rt.specialist_chat.facts(rt.specialists.get("malhas"))
    found = facts.lookup("app:linkcraft")
    assert found["explained"][0]["text"].startswith("Worst first")
    assert facts.lookup("app:twincraft") is None


def test_the_vendors_site_as_an_address_means_its_api():
    """Owner's installation, 2026-10-25: https://openai.com typed as the address made every call
    go to https://openai.com/chat/completions and fail; the vendor's site means its API."""

    from plantcraft.specialists.profiles import vendor_endpoint

    assert vendor_endpoint("openai", "https://openai.com") == ""
    assert vendor_endpoint("openai", "https://api.openai.com/v1") == ""
    assert vendor_endpoint("anthropic", "https://www.anthropic.com") == ""
    assert vendor_endpoint("openai", LOCAL["endpoint"]) == LOCAL["endpoint"]
    assert vendor_endpoint("anthropic", "https://openai.com") == "https://openai.com"


class _Events(_Response):
    """A streamed answer: server-sent events, one ``data:`` line each."""

    headers = {"content-type": "text/event-stream"}

    def __init__(self, events):
        super().__init__(
            "".join(f"data: {json.dumps(item)}\n\n" for item in events).encode() + b"data: [DONE]\n"
        )


def test_the_answer_is_streamed_as_it_is_written_in_each_format(monkeypatch):
    """ "streaming da mensagem". With ``on_text`` set, each call asks for a
    stream and shows the text so far; tool calls still come through whole."""

    streams = [
        # OpenAI's Responses: a tool call, then the answer in two deltas.
        [
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "c1",
                            "name": "plant_clock",
                            "arguments": "{}",
                        }
                    ],
                },
            }
        ],  # fmt: skip
        [
            {"type": "response.output_text.delta", "delta": "FIC-101 "},
            {"type": "response.output_text.delta", "delta": "is worst."},
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "FIC-101 is worst."}],
                        }
                    ],
                },
            },  # fmt: skip
        ],
        # Chat completions: a tool call in pieces, then text.
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "t1",
                                    "function": {"name": "plant_", "arguments": '{"a"'},
                                }
                            ]
                        }
                    }
                ]
            },  # fmt: skip
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "clock", "arguments": ": 1}"}}
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },  # fmt: skip
        ],
        [
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo."}, "finish_reason": "stop"}]},
        ],  # fmt: skip
        # Anthropic: a tool_use block from JSON pieces, then text.
        [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "u1", "name": "plant_clock"},
            },  # fmt: skip
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"b": '},
            },  # fmt: skip
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": "2}"},
            },  # fmt: skip
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        ],
        [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },  # fmt: skip
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Done"},
            },  # fmt: skip
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        ],
    ]
    sent = []

    def urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return _Events(streams.pop(0))

    monkeypatch.setattr(model_module, "_open", lambda request, timeout, proxy="": urlopen(request, timeout))  # fmt: skip
    tools = [{"name": "plant_clock", "description": "Now.", "input_schema": {"type": "object"}}]
    for model, expected, args in (
        (ChatModel("sk-x", provider="openai", model="gpt-5-nano"), "FIC-101 is worst.", {}),
        (
            ChatModel("", provider="openai", model="qwen3", endpoint=LOCAL["endpoint"]),
            "Hello.",
            {"a": 1},
        ),  # fmt: skip
        (ChatModel("sk-ant", provider="anthropic", model="claude"), "Done", {"b": 2}),
    ):
        seen, calls = [], []
        model.on_text = seen.append
        text = model.answer("Be brief.", [{"role": "user", "content": "hi"}], tool=lambda name, given: calls.append((name, given)) or "10:00", tools=tools)  # fmt: skip
        assert text == expected and calls == [("plant_clock", args)]
        assert seen[-1] == expected and "" in seen  # each call starts again
        assert sent[-1]["stream"] is True
    # A server that answers whole although asked to stream is read as before.
    monkeypatch.setattr(model_module, "_open", lambda request, timeout, proxy="": _Response(json.dumps({"choices": [{"message": {"content": "whole"}, "finish_reason": "stop"}]}).encode()))  # fmt: skip
    model = ChatModel("", provider="openai", model="qwen3", endpoint=LOCAL["endpoint"])
    model.on_text = lambda _text: None
    assert model.answer("Be brief.", [{"role": "user", "content": "hi"}]) == "whole"
