# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""The assistant's works: declared as data per page, offered by the button
beside the page's title, a context in fixed sections, and "create" works that only propose: the
person creates the object with one click, through the object's own route."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from plantcraft.api.routers.assistant_chat import PageInfo
from plantcraft.assistant_works import LIMITS, Work, WorkRegistry, envelope, render
from plantcraft_sdk.contributes import (
    AssistantTable,
    AssistantWork,
    ContributionsIn,
    check_fields,
    contributions,
    fields_schema,
)
from tests.test_assistant_chat import LOCAL, _ask
from tests.test_collaboration import _person, signed  # noqa: F401

NEW_ACTION = {
    "id": "new-action",
    "pages": ["actions"],
    "kind": "create",
    "level": "editor",
    "title": "Create an action",
    "instructions": "Collect the action's title and priority, then propose it.",
    "object": "action",
    "fields": [
        {"key": "title", "title": "Title", "required": True, "max_length": 200},
        {
            "key": "priority",
            "title": "Priority",
            "type": "choice",
            "options": ["low", "normal", "high"],
        },
        {"key": "due_at", "title": "Due", "type": "datetime"},
    ],
    "create": "/api/actions",
    "open": "/actions/{id}",
}
ASK = {
    "id": "about-actions",
    "pages": ["actions", "action"],
    "title": "Ask about these actions",
    "instructions": "Answer about the actions on this page.",
}


def test_the_sdk_checks_a_work_and_its_proposals():
    work = AssistantWork.model_validate(NEW_ACTION)
    with pytest.raises(ValidationError):
        AssistantWork.model_validate({**NEW_ACTION, "fields": []})  # create: fields
    with pytest.raises(ValidationError):
        AssistantWork.model_validate({**NEW_ACTION, "open": "/actions"})  # open: names the id
    with pytest.raises(ValidationError):
        AssistantWork.model_validate({**ASK, "create": "/api/actions"})  # ask: no route
    clean, problems = check_fields(
        work.fields, {"priority": "urgent", "extra": 1, "due_at": "soon"}
    )
    assert clean == {}
    assert problems == [
        "Unknown field 'extra'.",
        "Title (title) is required.",
        "Priority is one of: low, normal, high.",
        "Due is a date and time (ISO 8601).",
    ]
    assert check_fields(work.fields, {"title": "Check FV-101", "priority": "high"}) == (
        {"title": "Check FV-101", "priority": "high"},
        [],
    )
    schema = fields_schema(work.fields)
    assert schema["required"] == ["title"] and schema["additionalProperties"] is False
    assert schema["properties"]["priority"]["enum"] == ["low", "normal", "high"]
    body = contributions(
        {
            "app": {"id": "linkcraft", "version": "1.0.0"},
            "contributes": {"assistant": {"works": [ASK]}},
        }
    )
    assert ContributionsIn.model_validate(body).contributes.assistant.works[0].id == "about-actions"


def test_the_registry_offers_each_page_its_works_by_access_level():
    app_work = {**NEW_ACTION, "id": "new-block", "pages": ["blocks"], "object": "block",
                "create": "/link/api/blocks", "open": "/link/blocks/{id}"}  # fmt: skip
    outside = {**app_work, "id": "elsewhere", "create": "/api/actions"}
    rows = [{"app": "linkcraft", "contributes": {"assistant": {"works": [app_work, outside, ASK]}}}]
    registry = WorkRegistry(
        lambda apps: [row for row in rows if row["app"] in apps],
        lambda: {"linkcraft": "/link/"},
        platform=[AssistantWork.model_validate(ASK), AssistantWork.model_validate(NEW_ACTION)],
    )
    keys = [work.key for work in registry.all()]
    # A route outside the app's prefix is refused; the platform's and the app's works stay apart.
    assert keys == [
        "processcraft:about-actions",
        "processcraft:new-action",
        "linkcraft:new-block",
        "linkcraft:about-actions",
    ]
    assert [w.key for w in registry.for_page("processcraft:actions", "editor")] == [
        "processcraft:new-action",
        "processcraft:about-actions",
    ]
    assert [w.key for w in registry.for_page("processcraft:actions", "viewer")] == [
        "processcraft:about-actions"
    ]
    assert registry.for_page("processcraft:actions", None) == []
    public = registry.get("linkcraft:new-block").public()
    assert public["create"] == "/link/api/blocks" and public["fields"][0]["key"] == "title"


def test_the_context_has_fixed_sections_each_within_its_limit():
    work = Work("processcraft", AssistantWork.model_validate(NEW_ACTION))
    sections = envelope(
        work,
        place="Desk › Actions",
        page="processcraft:actions",
        subject={"ref": "asset:FIC-101", "title": "FIC-101"},
        facts={"open": 4, "note": "x" * 5000},
        view={"filters": {"state": "open"}, "rows": [f"action:{n}" for n in range(200)]},
        person={"username": "ana", "level": "editor"},
    )
    assert list(sections) == ["version", "work", "place", "subject", "view", "fields", "person"]
    assert sections["subject"]["facts"]["note"] == "x" * 300  # facts are short
    assert len(sections["view"]["rows"]) == 50  # the ids on screen, not every row
    text = render(sections)
    assert text.startswith("[assistant-context/1]")
    assert [line for line in text.splitlines() if line.startswith("## ")] == [
        "## work", "## place", "## subject", "## view", "## fields", "## person",
    ]  # fmt: skip
    assert len(text) < sum(LIMITS.values()) + 400


class ProposingModel:
    """Proposes once with a missing field, then again with every field."""

    systems: list[str] = []
    answers: list = []

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        self.label = f"Local · {model}"

    def answer(self, system, messages, tool=None, tools=None):
        ProposingModel.systems.append(system)
        assert "propose" in {item["name"] for item in tools}
        ProposingModel.answers = [
            tool("propose", {"fields": {"priority": "high"}}),
            tool("propose", {"fields": {"title": "Check FV-101 stiction", "priority": "high"}}),
        ]
        return "The card holds the action: Check FV-101 stiction, high priority."


def test_a_create_work_proposes_and_the_person_creates_through_the_objects_route(signed):
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = ProposingModel
    rt.assistant.works = WorkRegistry(
        platform=[AssistantWork.model_validate(NEW_ACTION), AssistantWork.model_validate(ASK)]
    )
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    offered = signed.get("/api/assistant/works", params={"page": "processcraft:actions"}).json()
    assert [item["key"] for item in offered["works"]] == [
        "processcraft:new-action",
        "processcraft:about-actions",
    ]
    page = {
        "page": "processcraft:actions",
        "facts": {"open": 3},
        "view": {"filters": {"mine": True}},
    }
    wrong = signed.post(
        "/api/assistant/chats",
        json={
            "text": "x",
            "work": "processcraft:new-action",
            "page": {**page, "page": "processcraft:assets"},
        },
    )
    assert wrong.status_code == 422
    chat_id, view = _ask(
        signed,
        "New action for FV-101",
        work="processcraft:new-action",
        page=page,
        place="Desk › Actions",
    )
    assert (
        ProposingModel.answers[0]["ok"] is False
        and "Title (title) is required." in ProposingModel.answers[0]["problems"]
    )
    assert ProposingModel.answers[1]["ok"] is True
    system = ProposingModel.systems[-1]
    assert "[assistant-context/1]" in system and "creates a new object (action)" in system
    assert "## fields" in system and "call propose" in system
    answer = view["messages"][-1]
    [card] = answer["meta"]["proposals"]
    drawn = card.pop("card")
    assert drawn["create"] == "/api/actions" and drawn["open"] == "/actions/{id}"
    assert drawn["app"] == "processcraft" and [f["key"] for f in drawn["fields"]] == [
        "title", "priority", "due_at",
    ]  # fmt: skip
    assert card == {
        "work": "processcraft:new-action",
        "object": "action",
        "fields": {"title": "Check FV-101 stiction", "priority": "high"},
        "state": "proposed",
    }
    # Nothing was created by the model: the person clicks Create, the page calls the route.
    created = signed.post("/api/actions", json=card["fields"]).json()
    recorded = signed.post(
        f"/api/assistant/chats/{chat_id}/proposals",
        json={"message_id": answer["message_id"], "index": 0, "state": "created",
              "ref": f"action:{created['action_id']}", "href": f"/actions/{created['action_id']}"},
    )  # fmt: skip
    assert recorded.status_code == 200 and recorded.json()["proposal"]["state"] == "created"
    after = signed.get(f"/api/assistant/chats/{chat_id}").json()["messages"][-1]
    assert after["meta"]["proposals"][0]["ref"] == f"action:{created['action_id']}"
    actions = [item["action"] for item in rt.workspace.audit.list()]
    assert "assistant.proposed" in actions and "assistant.proposal_created" in actions
    missing = signed.post(
        f"/api/assistant/chats/{chat_id}/proposals",
        json={"message_id": answer["message_id"], "index": 3, "state": "discarded"},
    )
    assert missing.status_code == 404


def test_viewers_get_only_ask_works_and_cannot_start_a_create_one(signed):
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = ProposingModel
    rt.assistant.works = WorkRegistry(
        platform=[AssistantWork.model_validate(NEW_ACTION), AssistantWork.model_validate(ASK)]
    )
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    viewer = _person(signed, "vera", level="viewer")
    offered = viewer.get("/api/assistant/works", params={"page": "processcraft:actions"}).json()
    assert [item["key"] for item in offered["works"]] == [
        "processcraft:about-actions",
    ]
    refused = viewer.post(
        "/api/assistant/chats",
        json={
            "text": "x",
            "work": "processcraft:new-action",
            "page": {"page": "processcraft:actions"},
        },
    )
    assert refused.status_code == 404


DESK_PAGES = {
    "processcraft:actions": [
        "processcraft:new-action",
        "processcraft:about-actions",
        "processcraft:find-actions",
    ],
    "processcraft:action": [
        "processcraft:new-action",
        "processcraft:about-action",
        "processcraft:action-next",
    ],
    "processcraft:calendar": ["processcraft:new-event", "processcraft:about-calendar"],
    "processcraft:notes": ["processcraft:about-notes", "processcraft:find-notes"],
    "processcraft:todo": ["processcraft:about-todo", "processcraft:todo-actions"],
    "processcraft:notebooks": ["processcraft:about-notebooks", "processcraft:notebook-kit"],
}


def test_desk_offers_its_works_and_each_create_route_takes_the_cards_fields(signed):
    """Points 1-6 of the plan: Actions (create, ask), an action (ask), Calendar (create, ask),
    Notes, To-do and Notebooks (ask only). A card's fields, as the panel sends them, create the
    object through the page's own route."""

    rt = signed.app.state.runtime
    rt.assistant.works = WorkRegistry()  # PlantCraft's own works only
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    for page, keys in DESK_PAGES.items():
        offered = signed.get("/api/assistant/works", params={"page": page}).json()["works"]
        assert [item["key"] for item in offered] == keys, page
    assert {w.key for w in rt.assistant.works.all() if w.spec.kind == "create"} == {
        "processcraft:new-action", "processcraft:new-event", "processcraft:new-asset",
    }  # fmt: skip
    action = rt.assistant.works.get("processcraft:new-action")
    fields, problems = action.check(
        {"title": "Check FV-101 stiction", "priority": "high", "due_at": "2026-10-30",
         "refs": ["asset:FIC-101"]}
    )  # fmt: skip
    assert problems == []
    made = signed.post(action.spec.create, json=fields)
    assert made.status_code == 201 and made.json()["action_id"]
    event = rt.assistant.works.get("processcraft:new-event")
    fields, problems = event.check(
        {"title": "Turnaround meeting", "start": "2026-10-27T12:00:00.000Z", "all_day": False}
    )
    assert problems == []
    made = signed.post(event.spec.create, json=fields)
    assert made.status_code == 201 and made.json()["event_id"]
    # A viewer adds events to their own calendar, and gets no action to create.
    viewer = _person(signed, "vera", level="viewer")
    offered = viewer.get("/api/assistant/works", params={"page": "processcraft:calendar"}).json()
    assert [item["key"] for item in offered["works"]] == DESK_PAGES["processcraft:calendar"]
    offered = viewer.get("/api/assistant/works", params={"page": "processcraft:actions"}).json()
    assert [item["key"] for item in offered["works"]] == [
        "processcraft:about-actions",
        "processcraft:find-actions",
    ]


ASSET_PAGES = {
    "processcraft:assets": ["processcraft:new-asset", "processcraft:about-assets", "processcraft:find-assets"],
    "processcraft:asset": ["processcraft:new-action", "processcraft:asset-now", "processcraft:asset-plot", "processcraft:asset-signal", "processcraft:asset-conclusions"],
}  # fmt: skip


def test_assets_offer_their_works_and_an_admin_creates_an_asset_from_the_card(signed):
    """Points 7-8 of the plan: the tree (create, ask) and one asset (three asks). Only an admin
    creates assets, so only an admin is offered the create work."""

    rt = signed.app.state.runtime
    rt.assistant.works = WorkRegistry()
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    for page, keys in ASSET_PAGES.items():
        offered = signed.get("/api/assistant/works", params={"page": page}).json()["works"]
        assert [item["key"] for item in offered] == keys, page
    work = rt.assistant.works.get("processcraft:new-asset")
    fields, problems = work.check(
        {"asset_id": "FV-2001", "name": "Feed valve", "kind": "equipment",
         "description": "The feed control valve"}
    )  # fmt: skip
    assert problems == []
    made = signed.post(work.spec.create, json=fields)
    assert made.status_code == 201 and made.json()["asset_id"] == "FV-2001"
    editor = _person(signed, "eddie", level="editor")
    offered = editor.get("/api/assistant/works", params={"page": "processcraft:assets"}).json()
    assert [item["key"] for item in offered["works"]] == [
        "processcraft:about-assets",
        "processcraft:find-assets",
    ]


MORE_PAGES = {
    "processcraft:desk-today": [
        "processcraft:new-action",
        "processcraft:today",
        "processcraft:today-plan",
    ],
    "processcraft:attention": ["processcraft:new-action", "processcraft:about-attention"],
    "processcraft:asset-types": ["processcraft:about-types", "processcraft:type-choose"],
    "processcraft:help": ["processcraft:about-help"],
    "processcraft:executions": ["processcraft:about-executions", "processcraft:executions-late"],
}


def test_more_pages_offer_an_ask_work(signed):
    """Owner, 2026-10-25 (evening): the assistant on more pages: Today, Needs attention, Types,
    Help and Executions each offer one ask work; a page that sends too many rows is cut, not
    refused."""

    rt = signed.app.state.runtime
    rt.assistant.works = WorkRegistry()
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    for page, keys in MORE_PAGES.items():
        offered = signed.get("/api/assistant/works", params={"page": page}).json()["works"]
        assert [item["key"] for item in offered] == keys, page
    rows = [f"row {number} " + "x" * 200 for number in range(200)]
    info = PageInfo(page="processcraft:attention", view={"rows": rows, "status": ["alarm"]})
    assert 0 < len(info.view["rows"]) < 200 and info.view["status"] == ["alarm"]


def test_a_work_may_continue_in_the_objects_own_form():
    """A block's code or an algorithm's diagram is finished in its own form: the work names the
    form instead of a create route, and the card hands the fields over."""

    form = {**NEW_ACTION, "id": "new-block", "object": "block", "create": None, "open": None,
            "form": "/link/blocks/new"}  # fmt: skip
    spec = AssistantWork.model_validate(form)
    with pytest.raises(ValidationError):
        AssistantWork.model_validate({**form, "create": "/link/api/blocks"})  # one or the other
    with pytest.raises(ValidationError):
        AssistantWork.model_validate({**form, "open": "/link/blocks/{id}"})  # the form opens it
    with pytest.raises(ValidationError):
        AssistantWork.model_validate({**ASK, "form": "/link/blocks/new"})  # ask: no form
    rows = [{"app": "linkcraft", "contributes": {"assistant": {"works": [form]}}}]
    registry = WorkRegistry(lambda apps: rows, lambda: {"linkcraft": "/link/"}, platform=[])
    [work] = registry.all()
    assert work.public()["form"] == "/link/blocks/new"
    assert "own form filled in" in work.tool()["description"]
    elsewhere = WorkRegistry(lambda apps: rows, lambda: {"linkcraft": "/other/"}, platform=[])
    assert elsewhere.all() == []  # a form outside the app is refused like a route
    assert spec.form and spec.create is None


def test_an_app_offers_a_platform_work_on_its_own_pages():
    """Creating an action from an alarm: the work and its route stay PlantCraft's, the page is the
    app's. An offer of a work PlantCraft does not have offers nothing."""

    offers = [{"work": "new-action", "pages": ["alarm"]}, {"work": "no-such-work", "pages": ["x"]}]
    rows = [{"app": "alarmcraft", "contributes": {"assistant": {"offers": offers}}}]
    registry = WorkRegistry(lambda apps: rows, lambda: {"alarmcraft": "/alarms/"})
    found = registry.for_page("alarmcraft:alarm", "editor")
    assert [work.key for work in found] == ["processcraft:new-action"]
    assert found[0].spec.create == "/api/actions"
    assert registry.for_page("alarmcraft:alarm", "viewer") == []  # the work's level still holds
    assert registry.for_page("alarmcraft:x", "admin") == []
    assert "alarmcraft:alarm" in registry.get("processcraft:new-action").pages()
    with pytest.raises(ValidationError):
        AssistantTable.model_validate({"offers": [offers[0], offers[0]]})


def test_a_work_sends_only_its_context_and_names_the_pages_object_in_its_form(signed):
    """each question with its own context, and works on the object a page
    shows ("help me change this block"). A work keeps the facts and view it names; a form or
    route holding "{subject}" gets the id of the chat's object."""

    explain = AssistantWork.model_validate(
        {**ASK, "id": "explain-block", "pages": ["block"], "context": ["code", "summary"]}
    )
    sections = envelope(
        Work("linkcraft", explain),
        page="linkcraft:block",
        subject={"ref": "block:linkcraft/rate", "title": "Rate"},
        facts={"code": "def run(...)", "summary": "Rate of change", "used_by": ["a", "b"]},
        view={"tab": "code"},
    )
    assert sections["subject"]["facts"] == {"code": "def run(...)", "summary": "Rate of change"}
    assert "view" not in sections
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = ProposingModel
    change = {
        **NEW_ACTION,
        "id": "change-action",
        "pages": ["action"],
        "open": None,
        "create": None,
        "form": "/actions/{subject}/edit",
    }
    rt.assistant.works = WorkRegistry(platform=[AssistantWork.model_validate(change)])
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    page = {"page": "processcraft:action", "subject": "action:42"}
    _chat, view = _ask(signed, "Change it", work="processcraft:change-action", page=page)
    [card] = view["messages"][-1]["meta"]["proposals"]
    assert card["card"]["form"] == "/actions/42/edit"


def test_an_answer_that_proposed_says_prepared_not_created() -> None:
    """D11 (2026-10-31): after a proposal the model wrote "I created an action"; only the card's
    button creates it."""

    from plantcraft.assistant_chat.engine import prepared_not_created

    assert prepared_not_created("I created an action for P-101.") == (
        "I prepared an action for P-101."
    )
    assert prepared_not_created("I've added a note and we have registered an event.") == (
        "I've prepared a note and we have prepared an event."
    )
    assert prepared_not_created("Criei uma ação.") == "Preparei uma ação."
    assert prepared_not_created("The pump was created in 2019.") == (
        "The pump was created in 2019."
    )
