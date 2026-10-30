"""Messages, specialists (robot users) and follow-up actions (docs/collaboration.md)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "senha-forte-1"
KEY = "sk-ant-test-0123456789abcd"


def _scenario(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/,dashcraft=/dash/")
    monkeypatch.delenv("PLANTCRAFT_LLM", raising=False)


@pytest.fixture()
def signed(tmp_path, monkeypatch):
    """Sign-in on, signed in as the environment's administrator."""

    _scenario(tmp_path, monkeypatch)
    secret = tmp_path / "secret"
    secret.write_text("admin-secret")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    with TestClient(create_app()) as client:
        response = client.post("/api/login", json={"username": "admin", "password": "admin-secret"})
        assert response.status_code == 200
        yield client


def _person(client, username, level="editor"):
    response = client.post(
        "/api/users",
        json={
            "username": username,
            "display_name": username.title(),
            "role": "Engenharia",
            "password": PASSWORD,
            "access_level": level,
        },
    )
    assert response.status_code == 201, response.text
    other = TestClient(client.app)
    response = other.post("/api/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return other


def _specialist(client, **changes):
    body = {
        "username": "malhas",
        "display_name": "Especialista em malhas",
        "subject": "control loops",
        "instructions": "Be brief.",
        "apps": ["linkcraft"],
    }
    body.update(changes)
    response = client.post("/api/specialists", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _publish_result(client, subject="asset:FIC-101", status="warning"):
    rt = client.app.state.runtime
    rt.workspace.results.put_results(
        [
            {
                "app": "linkcraft",
                "subject": subject,
                "kind": "health",
                "status": status,
                "score": 61.0,
                "usable": None,
                "value": 61.0,
                "summary": "Valve stiction suspected",
                "detail": {"limiting_method": "stiction"},
                "at": "2026-10-20T10:00:00+00:00",
                "expires_at": None,
            }
        ],
        now="2026-10-20T10:00:00+00:00",
        cutoff="2026-07-20T10:00:00+00:00",
    )


def _asset_id(client) -> str:
    rt = client.app.state.runtime
    loops = [item for item in rt.workspace.assets.list() if item["kind"] == "loop"]
    return loops[0]["asset_id"]


def _talk(client, text, member="malhas", **extra):
    response = client.post(
        "/api/messages/conversations", json={"members": [member], "text": text, **extra}
    )
    assert response.status_code == 201, response.text
    client.app.state.runtime.specialist_chat.drain(timeout=10)
    conversation_id = response.json()["conversation"]["conversation_id"]
    thread = client.get(f"/api/messages/conversations/{conversation_id}").json()
    return conversation_id, thread["messages"]


# Messages between people ---------------------------------------------------------


def test_people_talk_and_unread_counts_follow(signed):
    ana = _person(signed, "ana")
    response = ana.post(
        "/api/messages/conversations", json={"members": ["admin"], "text": "Bom dia"}
    )
    assert response.status_code == 201, response.text
    conversation_id = response.json()["conversation"]["conversation_id"]
    listing = signed.get("/api/messages/conversations").json()
    assert listing["unread"] == 1
    assert listing["items"][0]["display_title"] == "Ana"
    assert listing["items"][0]["last_message"]["text"] == "Bom dia"
    # The same two people reuse their direct conversation.
    again = signed.post("/api/messages/conversations", json={"members": ["ana"]}).json()
    assert again["conversation"]["conversation_id"] == conversation_id
    assert signed.post(f"/api/messages/conversations/{conversation_id}/read").json() == {
        "unread": 0
    }


def test_strangers_cannot_read_a_conversation(signed):
    ana = _person(signed, "ana")
    _person(signed, "bia")
    started = ana.post("/api/messages/conversations", json={"members": ["bia"], "text": "oi"})
    conversation_id = started.json()["conversation"]["conversation_id"]
    assert signed.get(f"/api/messages/conversations/{conversation_id}").status_code == 403
    assert signed.get("/api/messages/conversations/999999").status_code == 404


def test_a_conversation_reference_says_only_its_number_and_opens_messages(signed):
    ana = _person(signed, "ana")
    _person(signed, "bia")
    started = ana.post("/api/messages/conversations", json={"members": ["bia"], "text": "oi"})
    conversation_id = started.json()["conversation"]["conversation_id"]
    refs = signed.app.state.runtime.platform.refs
    found = refs.resolve(f"conversation:{conversation_id}")
    assert found["exists"] and found["href"] == f"/messages/{conversation_id}"
    assert found["title"] == f"Conversation #{conversation_id}"
    assert refs.resolve("conversation:999999")["exists"] is False


def test_dashboards_only_accounts_have_no_messages(signed):
    screen = _person(signed, "tela", level="dashboards")
    assert screen.get("/api/messages/conversations").status_code == 403


def test_plain_asset_ids_in_text_become_references(signed):
    _person(signed, "ana")
    asset = _asset_id(signed)
    response = signed.post(
        "/api/messages/conversations", json={"members": ["ana"], "text": f"Viu a {asset}?"}
    )
    refs = response.json()["message"]["refs"]
    assert [item["ref"] for item in refs] == [f"asset:{asset}"]
    assert refs[0]["href"] == f"/assets/{asset}"


# Specialists -----------------------------------------------------------------------


def test_admins_configure_specialists_and_keys_never_leave(signed, tmp_path):
    created = _specialist(signed, model={"enabled": True, "api_key": KEY})
    assert created["model"]["api_key_set"] is True
    assert created["model"]["api_key_hint"] == "…abcd"
    assert KEY not in json.dumps(signed.get("/api/specialists").json())
    keys = tmp_path / "specialist-keys.json"
    assert json.loads(keys.read_text()) == {"malhas": KEY}
    assert stat.S_IMODE(keys.stat().st_mode) == 0o600
    database = (tmp_path / "workspace.sqlite3").read_bytes()
    assert KEY.encode() not in database
    # null keeps the key, "" removes it.
    body = {"display_name": "Malhas", "apps": ["linkcraft"], "model": {"enabled": True}}
    kept = signed.put("/api/specialists/malhas", json=body).json()
    assert kept["model"]["api_key_set"] is True
    body["model"]["api_key"] = ""
    cleared = signed.put("/api/specialists/malhas", json=body).json()
    assert cleared["model"]["api_key_set"] is False
    # The robot is listed with the contacts but never as a person who signs in.
    assert signed.post("/api/login", json={"username": "malhas", "password": "x"}).status_code in {
        401,
        422,
    }
    users = [item["username"] for item in signed.get("/api/users").json()]
    assert "malhas" not in users


def test_only_admins_manage_specialists(signed):
    ana = _person(signed, "ana")
    assert ana.get("/api/specialists").status_code == 403
    assert (
        ana.post("/api/specialists", json={"username": "x1", "display_name": "X"}).status_code
        == 403
    )


def test_unknown_apps_and_bad_usernames_are_refused(signed):
    bad = {"username": "Bad Name", "display_name": "X"}
    assert signed.post("/api/specialists", json=bad).status_code == 422
    unknown = {"username": "abc", "display_name": "X", "apps": ["nope"]}
    assert signed.post("/api/specialists", json=unknown).status_code == 422
    _specialist(signed)
    assert (
        signed.post(
            "/api/specialists", json={"username": "malhas", "display_name": "Y"}
        ).status_code
        == 422
    )


def test_without_a_model_the_specialist_answers_from_the_apps_results(signed):
    _specialist(signed)
    asset = _asset_id(signed)
    _publish_result(signed, f"asset:{asset}")
    _id, messages = _talk(signed, f"Como está a #asset:{asset}?")
    reply = messages[-1]
    assert reply["author"] == "malhas"
    assert reply["author_kind"] == "specialist"
    assert reply["meta"]["writer"] == "script"
    assert "Valve stiction suspected" in reply["text"]
    assert "stiction" in reply["text"]
    profile = signed.get("/api/specialists").json()["items"][0]
    assert profile["answers"] == 1


def test_a_specialist_sees_only_its_apps(signed):
    _specialist(signed, apps=["dashcraft"])
    asset = _asset_id(signed)
    _publish_result(signed, f"asset:{asset}")
    _id, messages = _talk(signed, f"E a #asset:{asset}?")
    assert "Valve stiction suspected" not in messages[-1]["text"]


def test_specialists_refuse_to_change_things(signed):
    _specialist(signed)
    _id, messages = _talk(signed, "Mude o setpoint da malha para 50")
    assert "only read" in messages[-1]["text"]


def test_in_a_group_a_specialist_answers_only_when_mentioned(signed):
    _person(signed, "ana")
    _specialist(signed)
    response = signed.post(
        "/api/messages/conversations",
        json={"members": ["ana", "malhas"], "title": "Turno", "text": "Pessoal, reunião às 10"},
    )
    conversation_id = response.json()["conversation"]["conversation_id"]
    signed.app.state.runtime.specialist_chat.drain(timeout=10)
    thread = signed.get(f"/api/messages/conversations/{conversation_id}").json()
    assert [item["author"] for item in thread["messages"]] == ["admin"]
    signed.post(
        f"/api/messages/conversations/{conversation_id}/messages",
        json={"text": "@malhas o que precisa de atenção?"},
    )
    signed.app.state.runtime.specialist_chat.drain(timeout=10)
    thread = signed.get(f"/api/messages/conversations/{conversation_id}").json()
    assert thread["messages"][-1]["author"] == "malhas"


class FakeModel:
    calls: list[dict] = []
    ref = ""

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        self.label = f"Claude · {model or 'default'}"
        FakeModel.calls.append({"key": api_key, "model": model, "endpoint": endpoint})

    def answer(self, system, messages, tool=None, tools=None):
        found = tool("get_object", {"ref": FakeModel.ref})
        return f"Model saw {len(found['results'])} result(s)."


class BrokenModel(FakeModel):
    def answer(self, system, messages, tool=None, tools=None):
        raise RuntimeError("network down")


def test_with_a_model_turned_on_the_model_answers_with_read_only_tools(signed):
    rt = signed.app.state.runtime
    rt.specialist_chat.model_factory = FakeModel
    FakeModel.calls = []
    _specialist(signed, model={"enabled": True, "name": "claude-sonnet-5-5", "api_key": KEY})
    asset = _asset_id(signed)
    _publish_result(signed, f"asset:{asset}")
    FakeModel.ref = f"asset:{asset}"
    _id, messages = _talk(signed, f"#asset:{asset}")
    assert messages[-1]["text"] == "Model saw 1 result(s)."
    assert messages[-1]["meta"]["writer"] == "Claude · claude-sonnet-5-5"
    assert FakeModel.calls[-1]["key"] == KEY


def test_a_failing_model_falls_back_to_the_script(signed):
    signed.app.state.runtime.specialist_chat.model_factory = BrokenModel
    _specialist(signed, model={"enabled": True, "api_key": KEY})
    _id, messages = _talk(signed, "o que precisa de atenção?")
    assert messages[-1]["meta"] == {"writer": "script", "fallback": True}


def test_models_off_in_the_installation_wins_over_profiles(signed, monkeypatch):
    signed.app.state.runtime.specialist_chat.model_factory = FakeModel
    FakeModel.calls = []
    _specialist(signed, model={"enabled": True, "api_key": KEY})
    monkeypatch.setenv("PLANTCRAFT_LLM", "off")
    _id, messages = _talk(signed, "olá")
    assert messages[-1]["meta"]["writer"] == "script"
    assert FakeModel.calls == []
    assert signed.get("/api/specialists").json()["model_allowed"] is False
    assert signed.post("/api/specialists/malhas/test").json()["ok"] is False


def test_a_turned_off_specialist_says_so(signed):
    _specialist(signed)
    conversation_id, _ = _talk(signed, "olá")
    signed.put("/api/specialists/malhas", json={"display_name": "Malhas", "active": False})
    contacts = signed.get("/api/messages/contacts").json()
    assert contacts["specialists"] == []
    # Removing keeps the conversation and its messages.
    assert signed.delete("/api/specialists/malhas").json() == {"removed": "malhas"}
    thread = signed.get(f"/api/messages/conversations/{conversation_id}").json()
    assert len(thread["messages"]) == 2


# Actions -----------------------------------------------------------------------


def test_actions_are_created_changed_and_show_in_the_asset_timeline(signed):
    ana = _person(signed, "ana")
    asset = _asset_id(signed)
    created = signed.post(
        "/api/actions",
        json={
            "title": "Check the valve",
            "priority": "high",
            "owner": "ana",
            "due_at": "2026-10-25",
            "refs": [f"asset:{asset}"],
        },
    )
    assert created.status_code == 201, created.text
    action = created.json()
    assert action["status"] == "open"
    assert action["owner_name"] == "Ana"
    assert action["refs"][0]["href"] == f"/assets/{asset}"
    rt = signed.app.state.runtime
    timeline = rt.workspace.events.timeline(f"asset:{asset}")
    assert timeline[0]["kind"] == "action.created"
    # Ana's inbox counts it.
    token = ana.post("/api/v1/auth/token").json()["token"]
    inbox = ana.get("/api/v1/inbox", headers={"Authorization": f"Bearer {token}"}).json()
    assert inbox["open_actions"] == 1
    assert inbox["messages_url"] == "/messages"
    # Apps read the actions about the asset they show (the follow-up panel).
    about = ana.get(
        "/api/v1/actions",
        params={"ref": f"asset:{asset}"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert [item["action_id"] for item in about["items"]] == [action["action_id"]]
    assert about["items"][0]["status"] == "open" and "description" not in about["items"][0]
    elsewhere = ana.get(
        "/api/v1/actions",
        params={"ref": "asset:nowhere"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert elsewhere["items"] == []
    # Done: the status change is published and the action leaves the open list.
    body = {**{k: action[k] for k in ("title", "priority", "owner", "due_at")}, "status": "done"}
    body["refs"] = [f"asset:{asset}"]
    done = signed.put(f"/api/actions/{action['action_id']}", json=body).json()
    assert done["completed_at"]
    assert [item["kind"] for item in done["history"]] == ["created", "status"]
    assert rt.workspace.events.timeline(f"asset:{asset}")[0]["kind"] == "action.status_changed"
    listing = signed.get("/api/actions", params={"status": ["open", "in_progress"]}).json()
    assert listing["items"] == []
    assert signed.get("/api/actions", params={"ref": f"asset:{asset}"}).json()["items"]


def test_viewers_comment_but_do_not_create_actions(signed):
    viewer = _person(signed, "leo", level="viewer")
    action = signed.post("/api/actions", json={"title": "Review", "owner": "leo"}).json()
    assert viewer.post("/api/actions", json={"title": "Mine"}).status_code == 403
    commented = viewer.post(f"/api/actions/{action['action_id']}/comments", json={"text": "Ok"})
    assert commented.status_code == 201
    assert commented.json()["history"][-1]["kind"] == "comment"


def test_each_person_sees_their_actions_their_groups_and_below(signed):
    """an action goes to a person or a group; a leader sees below."""

    boss, lead, ana, eva = (_person(signed, name) for name in ("boss", "lead", "ana", "eva"))
    for body in (
        {"name": "Operations", "kind": "department", "coordinator": "boss"},
        {"name": "U-100", "coordinator": "lead", "members": ["ana"], "parent_id": "operations"},
        {"name": "Lab", "members": ["eva"]},
    ):
        assert signed.post("/api/groups", json=body).status_code == 201

    def create(client, **body):
        response = client.post("/api/actions", json={"title": "Task", **body})
        assert response.status_code == 201, response.text
        return response.json()["action_id"]

    to_ana = create(signed, title="For Ana", owner="ana")
    to_u100 = create(signed, title="For U-100", group_id="u-100")
    to_lab = create(signed, title="For the lab", group_id="lab")
    by_eva = create(eva, title="Eva's own note")
    assert signed.post("/api/actions", json={"title": "x", "group_id": "ghost"}).status_code == 422

    def seen(client, **params):
        return {
            item["action_id"] for item in client.get("/api/actions", params=params).json()["items"]
        }

    assert seen(ana) == {to_ana, to_u100}
    assert seen(ana, view="mine") == {to_ana}
    assert seen(ana, view="groups") == {to_u100}
    assert seen(lead) == {to_ana, to_u100}
    assert seen(boss) == {to_ana, to_u100}
    assert seen(eva) == {to_lab, by_eva}
    assert seen(eva, view="created") == {by_eva}
    assert seen(signed) == {to_ana, to_u100, to_lab, by_eva}
    assert seen(signed, group=["lab"]) == {to_lab}
    # Out of sight is not found, for reading and for changing.
    assert ana.get(f"/api/actions/{to_lab}").status_code == 404
    assert ana.post(f"/api/actions/{to_lab}/comments", json={"text": "?"}).status_code == 404
    action = ana.get(f"/api/actions/{to_u100}").json()
    assert action["group_name"] == "U-100"
    listing = ana.get("/api/actions").json()
    assert {"group_id": "u-100", "name": "U-100", "mine": True} in listing["groups"]
    assert [view["id"] for view in listing["views"]] == ["visible", "mine", "groups", "created"]
    # The home page and the reference picker count only what the person sees.
    home = eva.get("/api/home").json()
    assert home["journey"]["actions"]["open"] == 2
    found = eva.get("/api/messages/references", params={"q": "For"}).json()
    assert [item["detail"] for item in found if item["kind"] == "action"] == ["For the lab"]


def test_bad_actions_are_refused(signed):
    assert signed.post("/api/actions", json={"title": "x", "owner": "nobody"}).status_code == 422
    assert signed.post("/api/actions", json={"title": "x", "due_at": "amanhã"}).status_code == 422
    assert signed.post("/api/actions", json={"title": "x", "refs": ["no ref"]}).status_code == 422
    assert signed.get("/api/actions/999").status_code == 404


def test_the_inbox_counts_unread_messages_for_people_only(signed):
    ana = _person(signed, "ana")
    signed.post("/api/messages/conversations", json={"members": ["ana"], "text": "1"})
    token = ana.post("/api/v1/auth/token").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert ana.get("/api/v1/inbox", headers=headers).json()["unread_messages"] == 1
    assert TestClient(signed.app).get("/api/v1/inbox").status_code == 401


def test_the_home_page_path_counts_findings_runs_and_actions(signed):
    journey = signed.get("/api/home").json()["journey"]
    assert journey["last_run"] is None and journey["findings"] == {}
    assert journey["actions"] == {"open": 0, "overdue": 0, "done": 0, "total": 0}
    _publish_result(signed, "asset:FIC-101", "alarm")
    _publish_result(signed, "asset:PIC-102", "ok")
    rt = signed.app.state.runtime
    run = {
        "app": "linkcraft", "id": "r1", "name": "Round", "status": "done", "trigger": "schedule",
        "started_at": "2026-10-20T10:00:00+00:00", "finished_at": "2026-10-20T10:01:00+00:00",
        "subjects": [], "summary": "", "url": None,
    }  # fmt: skip
    rt.workspace.results.put_runs([run], now=run["finished_at"], cutoff="2026-07-20T00:00:00+00:00")
    signed.post("/api/actions", json={"title": "Late", "due_at": "2020-01-01"})
    done = signed.post("/api/actions", json={"title": "Fixed"}).json()
    signed.put(f"/api/actions/{done['action_id']}", json={"title": "Fixed", "status": "done"})
    journey = signed.get("/api/home").json()["journey"]
    assert journey["findings"] == {"linkcraft": {"alarm": 1, "total": 2}}
    assert journey["last_run"]["id"] == "r1"
    assert journey["actions"] == {"open": 1, "overdue": 1, "done": 1, "total": 2}


def test_the_home_page_lists_what_needs_someone_worst_first(signed):
    assert signed.get("/api/home").json()["attention"] == []
    _publish_result(signed, "asset:FIC-101", "warning")
    _publish_result(signed, "asset:PIC-102", "alarm")
    _publish_result(signed, "asset:TIC-103", "ok")
    attention = signed.get("/api/home").json()["attention"]
    assert [item["subject"] for item in attention] == ["asset:PIC-102", "asset:FIC-101"]
    first = attention[0]
    assert first["status"] == "alarm" and first["app"] == "linkcraft"
    # An asset opens on its page here, where every app's results meet.
    assert first["url"] == "/assets/PIC-102" and first["subject_kind"] == "asset"
