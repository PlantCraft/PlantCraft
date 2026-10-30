# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""What the apps explain (API v1 ``/knowledge``) and the assistant they open beside an object
(API v1 ``/assistant``): docs/collaboration.md, "The assistant of an app"."""

from __future__ import annotations

from fastapi.testclient import TestClient

from plantcraft.api.identity import issue_user_token
from tests.test_collaboration import _person, _specialist, signed  # noqa: F401

PROTOCOL = {
    "ref": "protocol:linkcraft/flow-health",
    "kind": "protocol",
    "title": "Flow loop health",
    "text": "Evaluates flow loops. Inputs: PV, SP, OP. Output: a health score from 0 to 100. "
    "Read a score under 60 as a loop that needs attention, first check valve stiction.",
    "url": "/link/protocols/flow-health",
}


def _service(client, app="linkcraft") -> dict[str, str]:
    created = client.post("/api/app-keys", json={"app_id": app, "label": "test"}).json()
    grant = client.post("/api/v1/auth/service-token", json={"app": app, "key": created["key"]})
    return {"Authorization": f"Bearer {grant.json()['token']}"}


def _user(client, username="admin") -> dict[str, str]:
    token = issue_user_token(client.app.state.runtime, username)["token"]
    return {"Authorization": f"Bearer {token}"}


def _run(client, headers, status="failed"):
    body = [
        {
            "id": "42",
            "name": "Flow loop health, unit 1",
            "status": status,
            "trigger": "manual",
            "started_at": "2026-10-21T10:00:00Z",
            "finished_at": "2026-10-21T10:05:00Z",
            "summary": "3 of 12 loops failed: no data for FIC-101.",
            "url": "/link/runs/42",
        }
    ]
    assert client.put("/api/v1/runs", json=body, headers=headers).json()["saved"] == 1


# Knowledge -------------------------------------------------------------------------


def test_apps_publish_search_and_remove_what_they_explain(signed):
    headers = _service(signed)
    report = {
        "ref": "run:linkcraft/42",
        "kind": "run_report",
        "title": "Run 42",
        "text": "FIC-101 had no data between 10:00 and 10:05.",
        "subjects": ["protocol:linkcraft/flow-health"],
        "transient": True,
    }
    saved = signed.put("/api/v1/knowledge", json=[PROTOCOL, report], headers=headers).json()
    assert saved == {"saved": 2, "errors": []}
    reader = _user(signed)
    about = signed.get("/api/v1/knowledge", params={"ref": PROTOCOL["ref"]}, headers=reader).json()
    # The protocol's own text first, then the run that names it.
    assert [item["ref"] for item in about] == [PROTOCOL["ref"], "run:linkcraft/42"]
    found = signed.get("/api/v1/knowledge", params={"q": "valve stiction"}, headers=reader).json()
    assert [item["ref"] for item in found] == [PROTOCOL["ref"]]
    deleted = signed.post(
        "/api/v1/knowledge/delete", json={"refs": [PROTOCOL["ref"]]}, headers=headers
    ).json()
    assert deleted == {"deleted": 1}
    assert signed.get("/api/v1/knowledge", params={"q": "stiction"}, headers=reader).json() == []


def test_knowledge_refuses_bad_refs_foreign_links_and_other_apps(signed):
    headers = _service(signed)
    bad = signed.put("/api/v1/knowledge", json=[{**PROTOCOL, "ref": "not a ref"}], headers=headers)
    assert bad.status_code == 422
    body = [{**PROTOCOL, "url": "/dash/x"}, {**PROTOCOL, "app": "dashcraft"}]
    receipt = signed.put("/api/v1/knowledge", json=body, headers=headers).json()
    assert receipt["saved"] == 0
    assert [item["index"] for item in receipt["errors"]] == [0, 1]
    people = signed.put("/api/v1/knowledge", json=[PROTOCOL], headers=_user(signed))
    assert people.status_code in (403, 200) and people.json().get("saved", 0) == 0


def test_runs_and_explained_objects_resolve_as_references(signed):
    headers = _service(signed)
    _run(signed, headers)
    signed.put("/api/v1/knowledge", json=[PROTOCOL], headers=headers)
    refs = signed.app.state.runtime.platform.refs
    run = refs.resolve("run:linkcraft/42", viewer="admin")
    assert run["exists"] and run["title"] == "Flow loop health, unit 1"
    assert run["href"] == "/link/runs/42" and run["status"] == "failed"
    protocol = refs.resolve(PROTOCOL["ref"], viewer="admin")
    assert protocol["exists"] and protocol["title"] == "Flow loop health"
    assert not refs.resolve("run:linkcraft/nope")["exists"]


# The assistant -----------------------------------------------------------------------


def test_the_assistant_suggests_the_specialists_of_the_objects_app(signed):
    headers = _user(signed)
    empty = signed.get("/api/v1/assistant", params={"ref": "run:linkcraft/42"}, headers=headers)
    assert empty.status_code == 200
    assert empty.json()["specialists"] == [] and empty.json()["specialists_url"]
    _specialist(signed)
    _specialist(signed, username="painel", display_name="Painel", apps=["dashcraft"])
    body = signed.get(
        "/api/v1/assistant", params={"ref": "run:linkcraft/42"}, headers=headers
    ).json()
    assert {item["username"] for item in body["specialists"]} == {"malhas", "painel"}
    assert body["suggested"] == ["malhas"]
    assert body["conversations"] == []
    # An app's algorithms and blocks are its own objects too.
    for ref in ("algorithm:linkcraft/loop_health", "block:linkcraft/dq.frozen"):
        found = signed.get("/api/v1/assistant", params={"ref": ref}, headers=headers).json()
        assert found["suggested"] == ["malhas"], ref


def test_asking_about_a_failed_run_answers_from_the_run_and_its_report(signed):
    _specialist(signed)
    service = _service(signed)
    _run(signed, service)
    signed.put(
        "/api/v1/knowledge",
        json=[
            {
                "ref": "run:linkcraft/42",
                "kind": "run_report",
                "title": "Run 42",
                "text": "FIC-101 had no data between 10:00 and 10:05; the other loops passed.",
                "transient": True,
            }
        ],
        headers=service,
    )
    headers = _user(signed)
    started = signed.post(
        "/api/v1/assistant/conversations",
        json={"specialist": "malhas", "ref": "run:linkcraft/42", "text": "Why did it fail?"},
        headers=headers,
    )
    assert started.status_code == 201, started.text
    conversation = started.json()["conversation"]
    assert conversation["title"] == "Flow loop health, unit 1"
    rt = signed.app.state.runtime
    rt.specialist_chat.drain(timeout=10)
    cid = conversation["conversation_id"]
    thread = signed.get(f"/api/v1/assistant/conversations/{cid}", headers=headers).json()
    reply = thread["messages"][-1]
    assert reply["author"] == "malhas"
    assert "3 of 12 loops failed" in reply["text"] and "FIC-101 had no data" in reply["text"]
    # A follow-up stays about the run.
    last = reply["message_id"]
    sent = signed.post(
        f"/api/v1/assistant/conversations/{cid}/messages",
        json={"text": "And now?"},
        headers=headers,
    )
    assert sent.status_code == 201
    rt.specialist_chat.drain(timeout=10)
    newer = signed.get(
        f"/api/v1/assistant/conversations/{cid}", params={"after": last}, headers=headers
    ).json()["messages"]
    assert newer[-1]["author"] == "malhas" and "run:linkcraft/42" in newer[-1]["text"]
    # The conversation is listed beside the run next time, and in Messages.
    listed = signed.get(
        "/api/v1/assistant", params={"ref": "run:linkcraft/42"}, headers=headers
    ).json()["conversations"]
    assert [item["conversation_id"] for item in listed] == [cid]
    inbox = signed.get("/api/messages/conversations").json()["items"]
    assert cid in [item["conversation_id"] for item in inbox]


def test_a_protocol_question_is_answered_from_what_the_app_explained(signed):
    _specialist(signed)
    signed.put("/api/v1/knowledge", json=[PROTOCOL], headers=_service(signed))
    headers = _user(signed)
    started = signed.post(
        "/api/v1/assistant/conversations",
        json={"specialist": "malhas", "ref": PROTOCOL["ref"], "text": "What does it evaluate?"},
        headers=headers,
    ).json()
    signed.app.state.runtime.specialist_chat.drain(timeout=10)
    cid = started["conversation"]["conversation_id"]
    reply = signed.get(f"/api/v1/assistant/conversations/{cid}", headers=headers).json()
    assert "Evaluates flow loops" in reply["messages"][-1]["text"]


def test_only_people_with_access_use_the_assistant(signed):
    _specialist(signed)
    _person(signed, "wall", level="dashboards")
    _person(signed, "ana")
    params = {"ref": "run:linkcraft/42"}
    stranger = TestClient(signed.app)
    assert stranger.get("/api/v1/assistant", params=params).status_code == 401
    assert (
        signed.get("/api/v1/assistant", params=params, headers=_user(signed, "wall")).status_code
        == 403
    )
    assert (
        signed.get("/api/v1/assistant", params=params, headers=_service(signed)).status_code == 403
    )
    assert (
        signed.get("/api/v1/assistant", params={"ref": "x"}, headers=_user(signed)).status_code
        == 422
    )
    body = {"specialist": "nobody", "ref": "run:linkcraft/42", "text": "hi"}
    refused = signed.post("/api/v1/assistant/conversations", json=body, headers=_user(signed))
    assert refused.status_code == 422
    body["specialist"] = "malhas"
    body["ref"] = "run:linkcraft/missing"
    missing = signed.post("/api/v1/assistant/conversations", json=body, headers=_user(signed))
    assert missing.status_code == 422
    # Someone else's conversation stays closed.
    service = _service(signed)
    _run(signed, service)
    body["ref"] = "run:linkcraft/42"
    started = signed.post("/api/v1/assistant/conversations", json=body, headers=_user(signed))
    cid = started.json()["conversation"]["conversation_id"]
    other = signed.get(f"/api/v1/assistant/conversations/{cid}", headers=_user(signed, "ana"))
    assert other.status_code == 403
