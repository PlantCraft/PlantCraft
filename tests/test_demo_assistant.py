"""The assistant for a public demo's visitors (``PLANTCRAFT_PUBLIC_DEMO_LLM``,
``plantcraft/assistant_chat/demo.py``): off by default; on, each visit asks in chats of its own,
a few questions, read-only, and what each answer spent is counted."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.assistant_chat.demo import DemoAssistant, DemoLimits, DemoQuestions
from plantcraft.db import Database, utc_text
from plantcraft.specialists.model import usage_of

ROOT = Path(__file__).resolve().parents[1]
EDGE = {"X-PlantCraft-Edge": "1"}
LOCAL = {
    "enabled": True,
    "provider": "openai",
    "name": "llama3.1:70b",
    "endpoint": "http://llm.plant.local:11434/v1",
}


class VisitModel:
    """A model that reads one signal list, answers, and says what the call spent."""

    tools: list[str] = []
    rounds: list[int] = []
    obeyed: list[str] = []

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        self.label = f"Local · {model}"
        self.rounds = 8
        self.usage = {"calls": 0, "input": 0, "cached": 0, "output": 0, "reasoning": 0}

    def answer(self, system, messages, tool=None, tools=None):
        VisitModel.tools = [item["name"] for item in tools or []]
        VisitModel.rounds.append(self.rounds)
        tool("search_signals", {"query": "pv"})
        self.usage = {"calls": 2, "input": 3000, "cached": 1000, "output": 200, "reasoning": 50}
        return f"Answered: {messages[-1]['content']}"


def _app(tmp_path, monkeypatch, **settings):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    secret = tmp_path / "secret"
    secret.write_text("admin-secret")
    for key, value in {
        "PLANTCRAFT_SCENARIO": str(path),
        "PLANTCRAFT_PREWARM_HISTORY": "false",
        "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
        "PLANTCRAFT_BASIC_AUTH_USERNAME": "admin",
        "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": str(secret),
        "PLANTCRAFT_PUBLIC_DEMO": "true",
        "PLANTCRAFT_PUBLIC_DEMO_PASSWORD": "plantcraft-demo",
        "PLANTCRAFT_PUBLIC_DEMO_SEATS": "4",
        "PLANTCRAFT_PUBLIC_DEMO_STATS_KEY": "stats-key",
        **settings,
    }.items():
        monkeypatch.setenv(key, value)
    return create_app()


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    """A public demo whose administrator connected a model; ``on`` sets the visitors' switch."""

    def made(**settings):
        app = _app(tmp_path, monkeypatch, **settings)
        admin = TestClient(app)
        admin.__enter__()
        assert admin.post(
            "/api/login", json={"username": "admin", "password": "admin-secret"}
        ).is_success
        assert (
            admin.post(
                "/api/users",
                json={
                    "username": "demo",
                    "display_name": "Demo visitor",
                    "role": "Visitor",
                    "password": "plantcraft-demo",
                    "access_level": "viewer",
                },
            ).status_code
            == 201
        )
        app.state.runtime.specialist_chat.model_factory = VisitModel
        assert admin.put("/api/language-model", json=LOCAL).status_code == 200
        made.clients.append(admin)
        return app

    made.clients = []
    yield made
    for client in made.clients:
        client.__exit__(None, None, None)


def _visit(app) -> TestClient:
    visitor = TestClient(app, headers=EDGE)
    assert visitor.post("/api/demo/enter", json={}).json()["entered"] is True
    return visitor


def _ask(visitor, text="Which signals are there?", **extra):
    response = visitor.post("/api/assistant/chats", json={"text": text, **extra})
    if response.status_code == 201:
        visitor.app.state.runtime.assistant.drain(timeout=20)
    return response


def test_off_by_default_visitors_only_read(demo):
    app = demo()
    visitor = _visit(app)
    state = visitor.get("/api/assistant").json()
    assert state["available"] is False and state["demo"] is True
    assert _ask(visitor).status_code == 403


def test_each_visit_asks_in_chats_of_its_own(demo):
    app = demo(PLANTCRAFT_PUBLIC_DEMO_LLM="on")
    first, second = _visit(app), _visit(app)
    state = first.get("/api/assistant").json()
    assert state["available"] is True and state["visit"] == {
        "questions": 10,
        "max_text": 1200,
        "left": 10,
    }
    asked = _ask(first)
    assert asked.status_code == 201, asked.text
    chat_id = asked.json()["chat"]["chat_id"]
    read = first.get(f"/api/assistant/chats/{chat_id}").json()
    assert read["chat"]["mine"] is True
    assert read["messages"][-1]["state"] == "done"
    assert read["messages"][-1]["text"].startswith("Answered")
    assert first.get("/api/assistant").json()["visit"]["left"] == 9
    assert chat_id in [item["chat_id"] for item in first.get("/api/assistant").json()["chats"]]
    # The next visitor never reads, nor writes in, another visit's chat.
    assert chat_id not in [item["chat_id"] for item in second.get("/api/assistant").json()["chats"]]
    assert second.get(f"/api/assistant/chats/{chat_id}").status_code == 404
    again = second.post(f"/api/assistant/chats/{chat_id}/messages", json={"text": "and?"})
    assert again.status_code == 404
    # Its own chat it continues; nothing else is written.
    assert (
        first.post(f"/api/assistant/chats/{chat_id}/messages", json={"text": "More?"}).status_code
        == 201
    )
    app.state.runtime.assistant.drain(timeout=20)
    for path, body in (
        (f"/api/assistant/chats/{chat_id}/keep", None),
        (f"/api/assistant/chats/{chat_id}/copy", None),
    ):
        assert first.post(path, json=body).status_code == 403
    assert first.patch(f"/api/assistant/chats/{chat_id}", json={"title": "x"}).status_code == 403
    assert first.delete(f"/api/assistant/chats/{chat_id}").status_code == 403
    assert (
        first.put(
            f"/api/assistant/chats/{chat_id}/sharing", json={"grants": ["everyone"]}
        ).status_code
        == 403
    )


def test_a_visit_only_asks_with_few_rounds(demo):
    app = demo(PLANTCRAFT_PUBLIC_DEMO_LLM="on")
    visitor = _visit(app)
    VisitModel.rounds = []
    assert _ask(visitor).status_code == 201
    # No card that creates, four rounds of reads.
    assert not [name for name in VisitModel.tools if name.startswith("propose")]
    assert VisitModel.rounds == [4]
    works = visitor.get("/api/assistant/works", params={"page": "processcraft:actions"}).json()
    assert works["works"] and all(item.get("kind") != "create" for item in works["works"])
    assert _ask(visitor, work="processcraft:new-action").status_code == 404
    assert _ask(visitor, profile="valve").status_code == 422
    assert _ask(visitor, text="x" * 1201).status_code == 422
    # A person the administrator created keeps the cards.
    admin = TestClient(app)
    assert admin.post(
        "/api/login", json={"username": "admin", "password": "admin-secret"}
    ).is_success
    assert _ask(admin).status_code == 201
    assert [name for name in VisitModel.tools if name.startswith("propose")]
    assert VisitModel.rounds[-1] == 8


def test_questions_per_visit_per_address_and_per_day(demo):
    app = demo(
        PLANTCRAFT_PUBLIC_DEMO_LLM="on",
        PLANTCRAFT_PUBLIC_DEMO_LLM_QUESTIONS="2",
        PLANTCRAFT_PUBLIC_DEMO_LLM_PER_ADDRESS="3",
    )
    first = _visit(app)
    assert _ask(first).status_code == 201
    assert _ask(first).status_code == 201
    refused = _ask(first)
    assert refused.status_code == 429 and "2 questions" in refused.json()["detail"]
    assert first.get("/api/assistant").json()["visit"]["left"] == 0
    # Another visit from the same address: one more, then the address's day is full.
    second = _visit(app)
    assert _ask(second).status_code == 201
    refused = _ask(second)
    assert refused.status_code == 429 and "from this address" in refused.json()["detail"]
    stats = (
        TestClient(app)
        .get("/api/demo/stats", headers={"Authorization": "Bearer stats-key"})
        .json()["assistant"]
    )
    assert stats["questions"] == 3 and stats["answered"] == 3
    assert stats["input"] == 9000 and stats["cached"] == 3000 and stats["output"] == 600
    assert stats["daily_limit"] == 600 and stats["questions_per_visit"] == 2


def test_the_days_cap_holds_all_visits(tmp_path):
    questions = DemoQuestions(Database(tmp_path / "q.sqlite3"))
    limits = DemoLimits()
    settings = DemoAssistant(questions=5, per_minute=100, per_address=100, daily=3)
    for number in range(3):
        assert limits.take(settings, questions, f"demo#visit:{number}", f"a{number}") is None
    refused = limits.take(settings, questions, "demo#visit:9", "b")
    assert refused and "today" in refused
    assert questions.count(since="") == 3


def test_a_minute_window_per_address(tmp_path):
    questions = DemoQuestions(Database(tmp_path / "q.sqlite3"))
    limits = DemoLimits()
    settings = DemoAssistant(questions=50, per_minute=2, per_address=100, daily=100)
    assert limits.take(settings, questions, "demo#visit:1", "a", now=0) is None
    assert limits.take(settings, questions, "demo#visit:1", "a", now=1) is None
    assert "minute" in (limits.take(settings, questions, "demo#visit:1", "a", now=2) or "")
    assert limits.take(settings, questions, "demo#visit:2", "b", now=2) is None
    assert limits.take(settings, questions, "demo#visit:1", "a", now=61) is None


def test_a_visits_chats_go_after_their_days(demo):
    app = demo(PLANTCRAFT_PUBLIC_DEMO_LLM="on")
    visitor = _visit(app)
    chat_id = _ask(visitor).json()["chat"]["chat_id"]
    store = app.state.runtime.assistant.store
    old = utc_text(datetime.now(timezone.utc) - timedelta(days=8))
    with store.db.write() as connection:
        connection.execute(
            "UPDATE assistant_chats SET updated_at = ? WHERE chat_id = ?", (old, chat_id)
        )
    assert store.forget_visits(7) == 1
    # The visitor account's own chats (the team's, as seeded) stay.
    kept = store.create("demo", "Seeded")
    assert store.forget_visits(0) == 0 and store.chat(kept["chat_id"], "demo")


def test_usage_is_read_from_each_service():
    responses = {
        "usage": {
            "input_tokens": 1200,
            "input_tokens_details": {"cached_tokens": 1024},
            "output_tokens": 300,
            "output_tokens_details": {"reasoning_tokens": 128},
        }
    }
    assert usage_of(responses) == {
        "calls": 1,
        "input": 1200,
        "cached": 1024,
        "output": 300,
        "reasoning": 128,
    }
    completions = {
        "usage": {
            "prompt_tokens": 900,
            "completion_tokens": 80,
            "prompt_tokens_details": {"cached_tokens": 0},
        }
    }
    assert usage_of(completions)["input"] == 900 and usage_of(completions)["output"] == 80
    messages = {"usage": {"input_tokens": 100, "cache_read_input_tokens": 400, "output_tokens": 50}}
    assert usage_of(messages) == {
        "calls": 1,
        "input": 500,
        "cached": 400,
        "output": 50,
        "reasoning": 0,
    }
    assert usage_of({}) == {"calls": 1, "input": 0, "cached": 0, "output": 0, "reasoning": 0}


def test_a_visits_answer_points_nowhere_outside_the_suite():
    from plantcraft.assistant_chat.demo import clean_answer

    planted = (
        "See ![chart](https://evil.example/x.png?d=FIC-101) and [the trend](/dash/trends/new) "
        "or [this](https://evil.example/?q=secret), [js](javascript:alert(1)), "
        "<img src=x onerror=alert(1)> <b>bold</b> https://evil.example/leak and www.evil.example."
    )
    cleaned = clean_answer(planted, 4000)
    assert "evil" not in cleaned and "javascript" not in cleaned and "<" not in cleaned
    assert "[the trend](/dash/trends/new)" in cleaned and "chart" in cleaned and "bold" in cleaned
    long = clean_answer("word " * 2000, 100)
    assert len(long) <= 102 and long.endswith("…")


def test_a_visits_answer_reads_at_most_its_tool_calls_and_last_turns(demo):
    app = demo(
        PLANTCRAFT_PUBLIC_DEMO_LLM="on",
        PLANTCRAFT_PUBLIC_DEMO_LLM_TOOL_CALLS="3",
        PLANTCRAFT_PUBLIC_DEMO_LLM_HISTORY="2",
    )
    seen: dict = {}

    class Greedy(VisitModel):
        def answer(self, system, messages, tool=None, tools=None):
            seen["turns"] = len(messages)
            seen["errors"] = 0
            for _ in range(10):
                try:
                    tool("search_signals", {"query": "pv"})
                except RuntimeError:
                    seen["errors"] += 1
            return "Done. <script>x</script>"

    app.state.runtime.specialist_chat.model_factory = Greedy
    visitor = _visit(app)
    chat_id = _ask(visitor).json()["chat"]["chat_id"]
    assert seen["errors"] == 7
    assert (
        visitor.post(
            f"/api/assistant/chats/{chat_id}/messages", json={"text": "And the next?"}
        ).status_code
        == 201
    )
    app.state.runtime.assistant.drain(timeout=20)
    assert seen["turns"] == 1
    answer = visitor.get(f"/api/assistant/chats/{chat_id}").json()["messages"][-1]
    assert answer["text"] == "Done. x"


def test_a_visit_reads_the_teams_chats_but_asks_only_in_its_own(demo):
    app = demo(PLANTCRAFT_PUBLIC_DEMO_LLM="on")
    store = app.state.runtime.assistant.store
    team = store.create("demo", "Which valves stick?")
    store.add(team["chat_id"], "user", "Which valves stick?")
    visitor = _visit(app)
    listed = [item["chat_id"] for item in visitor.get("/api/assistant").json()["chats"]]
    assert team["chat_id"] in listed
    read = visitor.get(f"/api/assistant/chats/{team['chat_id']}").json()
    assert read["chat"]["can_ask"] is False
    assert (
        visitor.post(
            f"/api/assistant/chats/{team['chat_id']}/messages", json={"text": "and?"}
        ).status_code
        == 404
    )
    own = _ask(visitor).json()["chat"]["chat_id"]
    assert visitor.get(f"/api/assistant/chats/{own}").json()["chat"]["can_ask"] is True


def test_another_viewer_of_the_demo_reads_but_never_asks(demo):
    app = demo(PLANTCRAFT_PUBLIC_DEMO_LLM="on")
    admin = TestClient(app)
    assert admin.post(
        "/api/login", json={"username": "admin", "password": "admin-secret"}
    ).is_success
    assert (
        admin.post(
            "/api/users",
            json={
                "username": "reader",
                "display_name": "Reader",
                "role": "Engineer",
                "password": "reader-password-1",
                "access_level": "viewer",
            },
        ).status_code
        == 201
    )
    reader = TestClient(app)
    assert reader.post(
        "/api/login", json={"username": "reader", "password": "reader-password-1"}
    ).is_success
    assert reader.get("/api/assistant").json()["available"] is False
    assert _ask(reader).status_code == 403
