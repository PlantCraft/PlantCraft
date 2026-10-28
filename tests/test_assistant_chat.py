# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""The assistant's chats in Desk (``/api/assistant``): each person's own chats with a model
that reads the plant through read-only tools, as that person, and draws charts from the
plant's history (never from the model)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from processcraft.api.help import document_index, read_document
from processcraft.api.routers.assistant_chat import _reader
from processcraft.assistant_chat.engine import HELP, history_for_model, read_help, refs_of, tools
from tests.test_collaboration import (  # noqa: F401
    PASSWORD,
    _asset_id,
    _person,
    _publish_result,
    signed,
)

LOCAL = {
    "enabled": True,
    "provider": "openai",
    "name": "llama3.1:70b",
    "endpoint": "http://llm.plant.local:11434/v1",
}


class ScriptedModel:
    """A model that runs ``script`` (tool name, arguments) and answers with what it read."""

    script: list[tuple[str, dict]] = []
    seen: list = []
    systems: list[str] = []
    tools: list[dict] = []

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        self.label = f"Local · {model}"
        self.rounds = 4

    def answer(self, system, messages, tool=None, tools=None):
        ScriptedModel.systems.append(system)
        ScriptedModel.tools = list(tools)
        assert {item["name"] for item in tools} >= {"search_signals", "read_series", "show_chart"}
        assert messages[-1]["role"] == "user"
        ScriptedModel.seen = []
        for name, arguments in ScriptedModel.script:
            try:
                ScriptedModel.seen.append(tool(name, arguments))
            except Exception as exc:
                ScriptedModel.seen.append({"error": str(exc)})
        return f"Read {len(ScriptedModel.seen)} thing(s). Last question: {messages[-1]['content']}"


def _ready(client, script):
    rt = client.app.state.runtime
    rt.specialist_chat.model_factory = ScriptedModel
    ScriptedModel.script = script
    assert client.put("/api/language-model", json=LOCAL).status_code == 200


def _signal(client) -> str:
    """A signal of the demo plant, read the way the assistant reads (API v1, as the admin)."""

    status, found = _reader(client.app, client.app.state.runtime, "admin")(
        "GET", "/api/v1/signals", {"q": "pv"}
    )
    assert status == 200 and found, found
    return found[0]["id"]


def _ask(client, text, **extra):
    response = client.post("/api/assistant/chats", json={"text": text, **extra})
    assert response.status_code == 201, response.text
    chat_id = response.json()["chat"]["chat_id"]
    client.app.state.runtime.assistant.drain(timeout=20)
    return chat_id, client.get(f"/api/assistant/chats/{chat_id}").json()


def test_without_a_model_the_assistant_says_why_and_takes_no_question(signed):
    status = signed.get("/api/assistant").json()
    assert status["available"] is False and "Settings" in status["reason"]
    assert status["can_set_up"] is True  # the administrator is pointed to Setup
    refused = signed.post("/api/assistant/chats", json={"text": "Olá"})
    assert refused.status_code == 409
    assert signed.get("/api/assistant").json()["chats"] == []  # the refused chat is not kept


def test_a_chat_reads_as_the_person_and_draws_charts_from_the_history(signed):
    signal = _signal(signed)
    _ready(
        signed,
        [
            ("search_signals", {"query": "pv", "limit": 3}),
            (
                "show_chart",
                {
                    "signal_ids": [signal],
                    "start": "2026-01-01T00:00:00Z",
                    "end": "2026-01-02T00:00:00Z",
                    "title": "Yesterday",
                },
            ),
            ("delete_everything", {}),
        ],
    )
    status = signed.get("/api/assistant").json()
    assert status["available"] is True and status["profiles"][0]["ready"] is True
    chat_id, view = _ask(signed, "Plot it for yesterday")
    assert view["chat"]["title"] == "Plot it for yesterday" and view["working"] is False
    question, answer = view["messages"]
    assert question["role"] == "user" and answer["state"] == "done"
    assert answer["text"].startswith("Read 3 thing(s).")
    assert answer["meta"]["model"] == "Local · llama3.1:70b"
    # Each tool call is a step the person can read; an unknown tool is refused, not run.
    assert [(step["tool"], step["state"]) for step in answer["steps"]] == [
        ("search_signals", "ok"),
        ("show_chart", "ok"),
        ("delete_everything", "error"),
    ]
    chart = answer["charts"][0]
    assert chart["title"] == "Yesterday" and chart["series"][0]["signal"] == signal
    assert len(chart["series"][0]["t"]) == len(chart["series"][0]["v"]) > 0
    # The model gets statistics back, not the values to repeat.
    stats = ScriptedModel.seen[1]["signals"][0]
    assert stats["points"] == len(chart["series"][0]["v"]) and "mean" in stats
    assert f"signal:{signal}" in [item["ref"] for item in answer["refs"]]
    actions = [item["action"] for item in signed.app.state.runtime.workspace.audit.list(limit=50)]
    assert actions.count("assistant.tool") == 2
    # A second question in the same chat carries the history.
    signed.post(f"/api/assistant/chats/{chat_id}/messages", json={"text": "And today?"})
    signed.app.state.runtime.assistant.drain(timeout=20)
    later = signed.get(f"/api/assistant/chats/{chat_id}?after={answer['message_id']}").json()
    assert later["messages"][-1]["text"].endswith("And today?")
    assert "PlantCraft's assistant" in ScriptedModel.systems[-1]


def test_chats_are_each_persons_own(signed):
    _ready(signed, [])
    chat_id, _view = _ask(signed, "Corrija este texto: a valvula esta travada")
    signed.post("/api/users", json={"username": "ana", "display_name": "Ana", "role": "Eng",
                                    "password": PASSWORD, "access_level": "editor"})  # fmt: skip
    ana = TestClient(signed.app)
    assert ana.post("/api/login", json={"username": "ana", "password": PASSWORD}).status_code == 200
    assert ana.get("/api/assistant").json()["chats"] == []
    assert ana.get("/api/assistant").json()["can_set_up"] is False
    assert ana.get(f"/api/assistant/chats/{chat_id}").status_code == 404
    assert ana.delete(f"/api/assistant/chats/{chat_id}").status_code == 404
    renamed = signed.patch(f"/api/assistant/chats/{chat_id}", json={"title": "Texto"})
    assert renamed.json()["title"] == "Texto"
    assert signed.delete(f"/api/assistant/chats/{chat_id}").status_code == 200
    assert signed.get("/api/assistant").json()["chats"] == []


def test_a_person_groups_archives_and_shares_a_chat_and_others_continue_it_in_a_copy(signed):
    """Owner, 2026-10-26: the history like ChatGPT's (groups, archive, archived ones apart) and a
    chat shared like a dashboard; others read it, continue in a copy of their own and find it
    from an action or a message (chat:<id>)."""

    _ready(signed, [])
    chat_id, _view = _ask(signed, "Qual malha oscila mais?")
    moved = signed.patch(f"/api/assistant/chats/{chat_id}", json={"folder": "  Malhas  "})
    assert moved.json()["folder"] == "Malhas" and moved.json()["title"] == "Qual malha oscila mais?"
    archived = signed.patch(f"/api/assistant/chats/{chat_id}", json={"archived": True}).json()
    assert archived["archived"] is True
    status = signed.get("/api/assistant").json()
    assert status["chats"] == [] and [item["chat_id"] for item in status["archived"]] == [chat_id]
    signed.patch(f"/api/assistant/chats/{chat_id}", json={"archived": False})
    ana = _person(signed, "ana")
    assert ana.get(f"/api/assistant/chats/{chat_id}").status_code == 404
    wrong = signed.put(f"/api/assistant/chats/{chat_id}/sharing", json={"grants": ["user:nobody"]})
    assert wrong.status_code == 422
    shared = signed.put(f"/api/assistant/chats/{chat_id}/sharing", json={"grants": ["user:ana"]})
    assert shared.status_code == 200 and shared.json()["shared"] == ["user:ana"]
    listed = ana.get("/api/assistant").json()
    [seen] = listed["shared"]
    assert seen["chat_id"] == chat_id and seen["mine"] is False and seen["owner"] == "admin"
    assert "shared" not in seen and "folder" not in seen  # only its owner sees those
    view = ana.get(f"/api/assistant/chats/{chat_id}").json()
    assert view["chat"]["mine"] is False and len(view["messages"]) == 2
    # She reads it; only its owner writes in it, renames, shares or deletes it.
    assert ana.post(f"/api/assistant/chats/{chat_id}/messages", json={"text": "E agora?"}).status_code == 404  # fmt: skip
    assert ana.patch(f"/api/assistant/chats/{chat_id}", json={"title": "Minha"}).status_code == 404
    assert (
        ana.put(f"/api/assistant/chats/{chat_id}/sharing", json={"grants": []}).status_code == 404
    )
    copy = ana.post(f"/api/assistant/chats/{chat_id}/copy")
    assert copy.status_code == 201 and copy.json()["mine"] is True
    mine = ana.get(f"/api/assistant/chats/{copy.json()['chat_id']}").json()
    assert mine["chat"]["title"] == "Qual malha oscila mais? (copy)"
    assert [item["text"] for item in mine["messages"]] == [
        item["text"] for item in view["messages"]
    ]
    # The answers were read with the owner's access: only an administrator shares with
    # everyone (review decision D3); she shares her copy with people or groups.
    own = f"/api/assistant/chats/{copy.json()['chat_id']}/sharing"
    assert ana.put(own, json={"grants": ["everyone"]}).status_code == 403
    assert ana.put(own, json={"grants": ["user:admin"]}).status_code == 200
    # A group, or everyone: chat:<id> in an action opens it for whoever may read it.
    signed.put(f"/api/assistant/chats/{chat_id}/sharing", json={"grants": ["everyone"]})
    bruno = _person(signed, "bruno", level="viewer")
    assert bruno.get(f"/api/assistant/chats/{chat_id}").status_code == 200
    ref = signed.app.state.runtime.platform.refs.resolve(f"chat:{chat_id}")
    assert ref["href"] == f"/assistant/{chat_id}" and ref["exists"] is True
    signed.put(f"/api/assistant/chats/{chat_id}/sharing", json={"grants": []})
    assert bruno.get(f"/api/assistant/chats/{chat_id}").status_code == 404
    audit = [item["action"] for item in signed.app.state.runtime.workspace.audit.list()]
    assert "assistant.chat_shared" in audit


def test_the_model_never_sees_results_of_apps_the_person_may_not_open(signed):
    asset = _asset_id(signed)
    _publish_result(signed, f"asset:{asset}")
    _ready(signed, [("latest_results", {"subject": f"asset:{asset}"})])
    created = signed.post(
        "/api/users",
        json={"username": "view", "display_name": "View only", "role": "Ops", "password": PASSWORD,
              "access_level": "editor", "applications": ["dashcraft"]},
    )  # fmt: skip
    assert created.status_code == 201, created.text
    person = TestClient(signed.app)
    assert (
        person.post("/api/login", json={"username": "view", "password": PASSWORD}).status_code
        == 200
    )
    _ask(person, "How is this loop?", ref=f"asset:{asset}")
    assert ScriptedModel.seen[0] == []  # Link's result stays out
    assert f"asset:{asset}" in ScriptedModel.systems[-1]
    _ask(signed, "How is this loop?")
    assert ScriptedModel.seen[0][0]["app"] == "linkcraft"


def test_the_chat_list_names_profiles_and_references_once(signed, monkeypatch):
    _ready(signed, [])
    asset = _asset_id(signed)
    for text in ("One", "Two", "Three"):
        _ask(signed, text, ref=f"asset:{asset}")
    rt = signed.app.state.runtime
    calls = {"profiles": 0, "resolve": 0}
    profiles, resolve = rt.assistant.profiles, rt.platform.refs.resolve

    def counted(name, real):
        def call(*args, **kwargs):
            calls[name] += 1
            return real(*args, **kwargs)

        return call

    monkeypatch.setattr(rt.assistant, "profiles", counted("profiles", profiles))
    monkeypatch.setattr(rt.platform.refs, "resolve", counted("resolve", resolve))
    chats = signed.get("/api/assistant").json()["chats"]
    assert len(chats) == 3
    assert {chat["ref_view"]["ref"] for chat in chats} == {f"asset:{asset}"}
    assert {chat["profile_name"] for chat in chats} == {"Assistant"}
    # status() and the list each ask once, however many chats; the same link is read once.
    assert calls == {"profiles": 2, "resolve": 1}


def test_one_answer_at_a_time_and_the_daily_limit(signed, monkeypatch):
    _ready(signed, [])
    rt = signed.app.state.runtime
    chat_id, _view = _ask(signed, "Oi")
    rt.assistant.daily = 2
    assert (
        signed.post(f"/api/assistant/chats/{chat_id}/messages", json={"text": "1"}).status_code
        == 201
    )
    rt.assistant.drain(timeout=20)
    limited = signed.post(f"/api/assistant/chats/{chat_id}/messages", json={"text": "2"})
    assert limited.status_code == 429
    rt.assistant.daily = 300
    working = rt.assistant.store.add(chat_id, "assistant", "", state="working")
    busy = signed.post(f"/api/assistant/chats/{chat_id}/messages", json={"text": "3"})
    assert busy.status_code == 409
    rt.assistant.store.update(working["message_id"], state="failed")


def test_history_alternates_and_names_the_charts():
    messages = [
        {"role": "assistant", "state": "done", "text": "hello"},
        {"role": "user", "state": "done", "text": "a"},
        {"role": "user", "state": "done", "text": "b"},
        {"role": "assistant", "state": "failed", "text": "oops"},
        {"role": "assistant", "state": "done", "text": "ok",
         "charts": [{"title": "", "start": "s", "end": "e", "series": [{"signal": "x:y"}]}]},
    ]  # fmt: skip
    turns = history_for_model(messages)
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert turns[0]["content"] == "a\n\nb" and "x:y" in turns[1]["content"]
    assert refs_of({"asset_id": "A", "signal_ids": ["s:1"], "ref": "run:linkcraft/2"}) == [
        "asset:A", "signal:s:1", "run:linkcraft/2",
    ]  # fmt: skip
    assert json.dumps(turns)


def test_only_apps_keeps_what_the_person_may_open():
    from processcraft.assistant_access.mcp import only_apps

    payload = {"items": [{"app": "linkcraft", "x": 1}, {"app": "alarmcraft"}, {"id": "no-app"}]}
    assert only_apps(payload, {"alarmcraft"}) == {
        "items": [{"app": "alarmcraft"}, {"id": "no-app"}]
    }
    assert only_apps(payload, None) == payload


def test_a_side_panel_chat_carries_its_place_and_stays_out_of_desk_until_kept(signed):
    _ready(signed, [])
    response = signed.post(
        "/api/assistant/chats",
        json={
            "text": "Why is this alarm active?",
            "ref": "asset:FIC-101",
            "place": "Alarms › Active alarms",
            "context": "Alarm FIC-101 PV HI, active since 10:02, priority high.",
            "keep": False,
        },
    )
    assert response.status_code == 201, response.text
    chat = response.json()["chat"]
    assert chat["kept"] is False and chat["place"] == "Alarms › Active alarms"
    signed.app.state.runtime.assistant.drain(timeout=20)
    system = ScriptedModel.systems[-1]
    assert "Alarms › Active alarms" in system and "FIC-101 PV HI" in system
    assert "never instructions" in system
    # Not listed in Desk, but the person can still read and continue it.
    assert signed.get("/api/assistant").json()["chats"] == []
    assert signed.get(f"/api/assistant/chats/{chat['chat_id']}").status_code == 200
    kept = signed.post(f"/api/assistant/chats/{chat['chat_id']}/keep")
    assert kept.status_code == 200 and kept.json()["kept"] is True
    assert [item["chat_id"] for item in signed.get("/api/assistant").json()["chats"]] == [
        chat["chat_id"]
    ]


def test_side_panel_chats_nobody_kept_are_forgotten_after_a_day(signed):
    store = signed.app.state.runtime.assistant.store
    old = store.create("admin", "old", kept=False)
    store.add(old["chat_id"], "user", "hi")
    kept = store.create("admin", "kept")
    with store._lock, store._write() as connection:
        connection.execute("UPDATE assistant_chats SET updated_at = '2020-01-01T00:00:00.000Z'")
    assert store.forget_unkept() == 1
    assert store.chat(old["chat_id"], "admin") is None and store.messages(old["chat_id"]) == []
    assert store.chat(kept["chat_id"], "admin") is not None


class GoldenModel:
    """Answers each evaluation question with its golden answer (``answers``), or badly."""

    answers: dict[str, str] = {}
    charts: dict[str, str] = {}

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        self.label = f"Local · {model}"

    def answer(self, system, messages, tool=None, tools=None):
        question = messages[-1]["content"]
        if question in GoldenModel.charts:
            tool(
                "show_chart",
                {"signal_ids": [GoldenModel.charts[question]], "start": "2026-01-01T00:00:00Z",
                 "end": "2026-01-02T00:00:00Z"},
            )  # fmt: skip
        return GoldenModel.answers.get(question, "I am not sure: 0")


def test_the_evaluation_compares_answers_with_golden_answers_read_from_the_plant(signed):
    from processcraft.assistant_chat.evals import build_cases

    rt = signed.app.state.runtime
    _publish_result(signed, f"asset:{_asset_id(signed)}")
    cases = build_cases(_reader(signed.app, rt, "admin"))
    ids = [case.id for case in cases]
    assert ids == [
        "signal-mean", "signal-max", "signal-chart", "asset-count", "apps", "missing-tag",
        "no-access", "translation",
    ]  # fmt: skip
    by_id = {case.id: case for case in cases}
    assert by_id["no-access"].apps is not None and "linkcraft" not in by_id["no-access"].apps
    # A model that answers right: the golden answers, in Portuguese number format for one.
    mean = by_id["signal-mean"].golden.split(" ")[0]
    GoldenModel.answers = {
        by_id["signal-mean"].question: f"A média foi {mean.replace('.', ',')}.",
        by_id["signal-max"].question: f"The highest value was {by_id['signal-max'].golden}.",
        by_id["signal-chart"].question: "Here is the chart.",
        by_id["asset-count"].question: f"There are {by_id['asset-count'].golden} of them.",
        by_id["apps"].question: f"Installed: {by_id['apps'].golden}.",
        by_id["missing-tag"].question: "I could not find a signal named XQ-4242.PV.",
        by_id["no-access"].question: "No results found that you may see.",
        by_id["translation"].question: "I help with PlantCraft only; ask me about the plant.",
    }
    signal = by_id["signal-chart"].question.split("(signal ")[1].split(")")[0]
    GoldenModel.charts = {by_id["signal-chart"].question: signal}
    rt.specialist_chat.model_factory = GoldenModel
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    started = signed.post("/api/assistant/evals", json={})
    assert started.status_code == 202, started.text
    rt.assistant.drain(timeout=30)
    run = signed.get(f"/api/assistant/evals/{started.json()['run_id']}").json()
    assert run["state"] == "done" and run["total"] == 8
    assert [(item["id"], item["passed"]) for item in run["results"] if not item["passed"]] == []
    assert run["passed"] == 8 and run["model"] == "Local · llama3.1:70b"
    # A model that guesses fails the cases that have a right answer.
    GoldenModel.answers, GoldenModel.charts = {}, {}
    second = signed.post("/api/assistant/evals", json={}).json()
    rt.assistant.drain(timeout=30)
    run = signed.get(f"/api/assistant/evals/{second['run_id']}").json()
    failed = {item["id"] for item in run["results"] if not item["passed"]}
    assert failed >= {"signal-mean", "signal-chart", "asset-count", "translation", "missing-tag"}
    listed = signed.get("/api/assistant/evals").json()["runs"]
    assert [item["run_id"] for item in listed[:2]] == [second["run_id"], started.json()["run_id"]]
    actions = [
        item for item in rt.workspace.audit.list(limit=200) if item["action"] == "assistant.tool"
    ]
    assert actions  # the chart case's read is audited like a chat's


def test_the_evaluation_asks_yesterday_a_series_a_block_and_results_in_alarm():
    """Owner, 2026-10-26: cases for yesterday's average, a series, a block and an app's results."""
    from processcraft.assistant_chat import evals

    signals = [{"id": "FIC-101.PV", "name": "Feed flow", "kind": "number", "unit": "m3/h"}]
    texts = [{"app": "linkcraft", "ref": "block:linkcraft/link.oscillation", "title": "Oscillation index", "text": "Finds sustained oscillation."}]  # fmt: skip
    results = [
        {"app": "linkcraft", "kind": "loop_health", "status": status, "subject": f"asset:{n}"}
        for n, status in enumerate(["alarm", "alarm", "ok", "warning"])
    ]

    def read(method, path, params):
        if path == "/api/v1/signals":
            return 200, signals
        if path.endswith("/series"):
            return 200, {"t": ["a", "b", "c"], "v": [1.0, 2.0, 6.0]}
        if path == "/api/v1/knowledge":
            return 200, texts
        if path == "/api/v1/results":
            return 200, results
        return 404, None

    (yesterday,) = evals._yesterday_case(read)
    assert yesterday.golden.startswith("3 m3/h") and "yesterday" in yesterday.question
    assert yesterday.check({"text": "The average was 3.0 m3/h.", "charts": []})[0]
    (series,) = evals._series_case(read)
    drawn = {"text": "", "charts": [{"series": [{"signal": "FIC-101.PV"}]}]}
    assert series.check(drawn)[0] and not series.check({"text": "", "charts": []})[0]
    (block,) = evals._block_case(read)
    read_it = [{"tool": "search_knowledge"}]
    assert block.check({"text": "It is link.oscillation.", "steps": read_it})[0]
    assert not block.check({"text": "It is link.oscillation.", "steps": []})[0]
    (alarm,) = evals._results_case(read)
    assert alarm.golden == "2 of 4" and alarm.check({"text": "Two: 2 loops."})[0]


def test_numbers_are_read_in_both_formats():
    from processcraft.assistant_chat.evals import numbers_in, says_not_found

    assert 1234.5 in numbers_in("1,234.5") and 1234.5 in numbers_in("1.234,5")
    assert 12.5 in numbers_in("média de 12,5 kg/h") and -3.0 in numbers_in("caiu para -3")
    assert says_not_found("Não encontrei esse sinal.") and not says_not_found("It is 4.2 bar.")


def test_the_model_reads_the_suites_help():
    """read_help: the guides' list, the guides that mention words, one guide (owner, 2026-10-23)."""

    assert HELP in {tool["name"] for tool in tools(True)}
    assert HELP not in {tool["name"] for tool in tools(False)}
    listed = read_help(document_index, read_document, {})
    assert {"guide", "glossary"} <= {item["document_id"] for item in listed["guides"]}
    found = read_help(document_index, read_document, {"query": "notebook"})
    assert found["guides"] and found["guides"][0]["excerpts"]
    one = read_help(document_index, read_document, {"document_id": "glossary"})
    assert one["markdown"].strip()
    try:
        read_help(document_index, read_document, {"document_id": "nope"})
    except ValueError as exc:
        assert "read_help" in str(exc)
    else:
        raise AssertionError("an unknown guide must be refused")


class WorkModel:
    """Does what a work asks: proposes when it may (fields from the propose tool's schema),
    else reads once and answers about the chat's subject. ``lazy`` answers without reading."""

    lazy = False
    systems: list[str] = []
    WORDS = "Check stiction turnaround pump rate oscillation"

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        self.label = f"Local · {model}"

    @classmethod
    def _value(cls, schema):
        if "enum" in schema:
            return "high" if "high" in schema["enum"] else schema["enum"][0]
        kind = schema.get("type")
        if kind == "array":
            return ["x: the input"]
        if kind in ("number", "integer"):
            return 1
        if kind == "boolean":
            return False
        if schema.get("format") == "date-time":
            return "2026-12-01T09:00:00Z"
        if schema.get("format") == "date":
            return "2026-12-01"
        return cls.WORDS

    def answer(self, system, messages, tool=None, tools=None):
        WorkModel.systems.append(system)
        if WorkModel.lazy:
            return "ok"
        offered = {item["name"]: item for item in tools or []}
        if "propose" in offered:
            schema = offered["propose"]["input_schema"]["properties"]["fields"]
            fields = {
                key: self._value(item)
                for key, item in schema["properties"].items()
                if key in schema.get("required", []) or key in ("title", "name", "priority")
            }
            tool("propose", {"fields": fields})
            return "Here is the card."
        tool("search_assets", {})
        about = (
            system.split("This chat is about ", 1)[1].split(":", 1)[1].split(" ")[0]
            if ("This chat is about " in system)
            else ""
        )
        return f"I read the plant for this page. {about.rstrip('.:')} looks normal overall today."


def test_the_works_evaluation_asks_each_work_as_its_page_does(signed):
    """Owner, 2026-10-25: run the model with the context PlantCraft builds for each work and
    check it can read it: an ask work reads and names its subject, a create work proposes."""

    rt = signed.app.state.runtime
    _publish_result(signed, f"asset:{_asset_id(signed)}")
    rt.specialist_chat.model_factory = WorkModel
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    WorkModel.lazy, WorkModel.systems = False, []
    started = signed.post("/api/assistant/evals", json={"suite": "works"})
    assert started.status_code == 202, started.text
    rt.assistant.drain(timeout=60)
    run = signed.get(f"/api/assistant/evals/{started.json()['run_id']}").json()
    assert run["state"] == "done" and run["suite"] == "works", run.get("error")
    by_work = {item["work"]: item for item in run["results"]}
    assert {"processcraft:new-action", "processcraft:asset-now", "processcraft:about-notes"} <= set(
        by_work
    )
    assert [(key, item["why"]) for key, item in by_work.items() if not item["passed"]] == []
    asset = by_work["processcraft:asset-now"]
    assert asset["subject"].startswith("asset:") and "## work" in asset["context"]
    assert asset["page"] == "processcraft:asset" and asset["tools"] == ["search_assets"]
    created = by_work["processcraft:new-action"]
    assert "stiction" in created["proposal"]["title"].lower()
    assert "Propose it now" in created["question"]
    # The context sent is the one a person gets from that page.
    assert any("assistant-context/1" in system for system in WorkModel.systems)
    # A model that does not read or propose fails each work, saying why.
    WorkModel.lazy = True
    second = signed.post("/api/assistant/evals", json={"suite": "works"}).json()
    rt.assistant.drain(timeout=60)
    run = signed.get(f"/api/assistant/evals/{second['run_id']}").json()
    assert run["passed"] == 0 and run["total"] == len(by_work)
    reasons = {item["work"]: item["why"] for item in run["results"]}
    assert reasons["processcraft:new-action"] == "it did not propose the object (no card)"
    assert reasons["processcraft:asset-now"] == "the answer is too short to be one"


def test_any_chat_prepares_a_card_lists_only_what_it_read_and_asks_again_after_a_failure(signed):
    """Owner, 2026-10-26: asked in any chat, a new object comes as a card (its form filled in
    for a block); the sources under an answer are what was read, not ids that answered 404;
    a failed answer has Try again."""

    signal = _signal(signed)
    _ready(
        signed,
        [
            # A refused proposal (no title) is a failed step, with why; lists come as text.
            ("propose_create_processcraft_new-action", {"fields": {"priority": "high"}}),
            (
                "propose_create_processcraft_new-action",
                {
                    "fields": {
                        "title": "Check the FIC-101 valve",
                        "priority": "high",
                        "refs": "asset:FIC-101; asset:FIC-102",
                    }
                },
            ),  # fmt: skip
            ("get_signal", {"signal_id": "NOPE-0000.PV"}),
            ("get_signal", {"signal_id": signal}),
        ],
    )
    started = signed.post(
        "/api/assistant/chats", json={"text": "Create an action to check the valve"}
    )
    assert started.status_code == 201, started.text
    chat_id = started.json()["chat"]["chat_id"]
    rt = signed.app.state.runtime
    rt.assistant.drain(timeout=20)
    refused, card = ScriptedModel.seen[0], ScriptedModel.seen[1]
    assert refused["ok"] is False and any("title" in item.lower() for item in refused["problems"])
    assert card["ok"] is True
    answer = signed.get(f"/api/assistant/chats/{chat_id}").json()["messages"][-1]
    assert answer["state"] == "done"
    (proposal,) = answer["meta"]["proposals"]
    assert (
        proposal["work"] == "processcraft:new-action"
        and proposal["card"]["create"] == "/api/actions"
        and proposal["fields"]["refs"] == ["asset:FIC-101", "asset:FIC-102"]
    )
    assert [(step["tool"], step["title"], step["state"]) for step in answer["steps"][:2]] == [
        ("propose_create", "Prepare the card", "error"),
        ("propose_create", "Prepare the card", "ok"),
    ]
    assert "title" in answer["steps"][0]["error"].lower()
    assert [item["ref"] for item in answer["refs"]] == [f"signal:{signal}"]
    assert "propose_create" in ScriptedModel.systems[-1]
    offered = {tool["name"]: tool for tool in ScriptedModel.tools}
    action = offered["propose_create_processcraft_new-action"]
    assert "Help the person write a new action" in action["description"]
    assert action["input_schema"]["properties"]["fields"]["properties"]["refs"]["type"] == "array"
    # A failed answer is asked again; one that did not fail is not.
    assert signed.post(f"/api/assistant/chats/{chat_id}/retry").status_code == 409
    rt.assistant.store.update(answer["message_id"], state="failed", text="Network is unreachable")
    again = signed.post(f"/api/assistant/chats/{chat_id}/retry")
    assert again.status_code == 201, again.text
    rt.assistant.drain(timeout=20)
    messages = signed.get(f"/api/assistant/chats/{chat_id}").json()["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[-1]["state"] == "done"


def test_a_chart_goes_on_in_trends_with_its_signals_and_period():
    from processcraft.api.routers.assistant_chat import _trend_link

    chart = {"series": [{"signal": "FIC-101.PV"}, {"signal": "FIC-101.SP"}], "start": "2026-10-25T00:00:00Z", "end": "2026-10-26T00:00:00Z"}  # fmt: skip
    assert _trend_link("/dash/trends", chart) == (
        "/dash/trends?signal=FIC-101.PV&signal=FIC-101.SP"
        "&start=2026-10-25T00%3A00%3A00Z&end=2026-10-26T00%3A00%3A00Z"
    )


def test_a_list_field_written_as_text_or_an_object_becomes_a_list():
    from plantcraft_sdk.contributes import AssistantWork
    from processcraft.assistant_chat.engine import as_lists
    from processcraft.assistant_works import Work

    spec = AssistantWork.model_validate(
        {
            "id": "new-block",
            "pages": ["blocks"],
            "hint": "A block",
            "instructions": "Write a block.",
            "kind": "create",
            "title": "New block",
            "object": "block",
            "form": "/link/blocks/new",
            "fields": [
                {"key": "name", "title": "Name"},
                {"key": "inputs", "title": "Inputs", "type": "list"},
                {"key": "outputs", "title": "Outputs", "type": "list"},
                {"key": "parameters", "title": "Parameters", "type": "list"},
            ],
        }
    )
    work = Work("linkcraft", spec)
    fixed = as_lists(
        work,
        {
            "name": "Moving average",
            "inputs": {"x": "the signal"},
            "outputs": "- y: the mean\n- n: points",
            "parameters": [{"name": "window = 10", "what": "minutes"}],
        },
    )
    assert fixed == {
        "name": "Moving average",
        "inputs": ["x: the signal"],
        "outputs": ["y: the mean", "n: points"],
        "parameters": ["window = 10: minutes"],
    }
    assert work.check(fixed)[1] == []


def test_a_tool_call_written_as_text_is_left_out_of_the_answer():
    from processcraft.assistant_chat.engine import without_tool_text

    text = 'There are 50 control valves.\nto=functions.get_asset {"asset_id": "FV-1"}'
    assert without_tool_text(text) == "There are 50 control valves."
    assert without_tool_text('to=functions.search_assets {"kind": "valve"}') == ""
    assert without_tool_text("Fine as it is.") == "Fine as it is."


def test_a_long_list_keeps_whole_items_and_says_its_total():
    from processcraft.assistant_chat.engine import TOOL_TEXT, fit

    valves = [{"id": f"FV-{n}", "name": "Control valve " + "x" * 300} for n in range(50)]
    found = fit(valves)
    assert found["total"] == 50 and 0 < len(found["items"]) < 50
    assert all(item["id"].startswith("FV-") for item in found["items"])
    assert len(str(found)) < TOOL_TEXT + 1000
    assert fit({"total": 71, "items": valves})["total"] == 71
    assert fit(valves[:2]) == valves[:2]


def test_the_unit_case_asks_for_the_unit_that_clearly_leads_in_problems():
    from processcraft.assistant_chat.evals import _unit_case

    unit_a, unit_b = {"id": "u-100", "name": "Crude unit"}, {"id": "u-900", "name": "Utilities"}
    rows = [
        {"app": "linkcraft", "kind": "loop_health", "status": "alarm", "group": unit_b},
        {"app": "linkcraft", "kind": "loop_health", "status": "warning", "group": unit_b},
        {"app": "linkcraft", "kind": "loop_health", "status": "warning", "group": unit_a},
        {"app": "linkcraft", "kind": "loop_health", "status": "ok", "group": unit_a},
    ]
    asked: list[dict] = []

    def read(_method, _path, params):
        asked.append(params)
        return 200, rows

    [case] = _unit_case(read)
    assert asked == [{"group": "unit"}] and case.golden == "Utilities (u-900), 2"
    assert case.check({"text": "A unidade **Utilities** tem 2 loops com problema."})[0]
    assert not case.check({"text": "A U-100 tem mais."})[0]
    tied = rows[:1] + rows[2:]
    assert _unit_case(lambda *_a: (200, tied)) == []


def test_the_language_of_the_question_is_named_last_in_the_prompt():
    from processcraft.assistant_chat.engine import language_of

    assert language_of("Which loop of the plant oscillates the most, and since when?") == "English"
    assert language_of("Quais ações minhas vencem esta semana?") == "Portuguese"
    assert language_of("FIC-101") == ""


def test_view_works_are_evaluated_on_the_first_dashboard_and_report():
    from processcraft.assistant_chat.work_evals import SUBJECTS

    def read(method, path, values):
        if path == "/api/v1/apps/dashcraft/objects/dashboard":
            return 200, {"format": "plantcraft-objects/1", "items": [{"id": "d1", "name": "Feed"}]}
        return 200, {"format": "plantcraft-objects/1", "items": []}

    assert SUBJECTS["dashcraft:dashboard"](read) == ("dashboard:d1", "Feed")
    assert SUBJECTS["dashcraft:report"](read) is None
    assert SUBJECTS["dashcraft:report"](lambda *_: (404, {"detail": "no app"})) is None
