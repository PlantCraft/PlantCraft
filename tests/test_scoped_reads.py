"""Nobody reads around their access (security review, 2026-10-26).

An action belongs to its owner, its group and those above (``docs/collaboration.md``): its
title must not reach anyone else through a link (``#action:42``), the events it publishes, an
asset's history or the assistant's ``recent_events``. A specialist in Messages answers the
people of the conversation, so it reads only the apps of its profile they all open and the
actions they all see.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from processcraft.api.identity import issue_user_token
from tests.test_collaboration import (  # noqa: F401 (the fixture)
    PASSWORD,
    _asset_id,
    _person,
    _publish_result,
    _specialist,
    _talk,
    signed,
)

SECRET = "Replace the lab's analyser"


def _lab_action(client, eva, about: str = "") -> int:
    assert client.post("/api/groups", json={"name": "Lab", "members": ["eva"]}).status_code == 201
    body = {"title": SECRET, "group_id": "lab"}
    if about:
        body["refs"] = [about]
    response = eva.post("/api/actions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["action_id"]


def _token(client, username: str) -> dict[str, str]:
    issued = issue_user_token(client.app.state.runtime, username)
    return {"Authorization": f"Bearer {issued['token']}"}


def test_an_action_out_of_sight_says_only_its_number(signed):  # noqa: F811
    eva = _person(signed, "eva")
    ana = _person(signed, "ana", "viewer")
    asset = _asset_id(signed)
    action_id = _lab_action(signed, eva, about=f"asset:{asset}")
    ref = f"action:{action_id}"

    assert ana.get(f"/api/actions/{action_id}").status_code == 404
    hidden = ana.get("/api/refs", params={"ref": ref}).json()[ref]
    assert SECRET not in hidden["title"] and hidden["hidden"] is True
    assert hidden["status"] is None
    timeline = ana.get(f"/api/refs/{ref}/timeline").json()
    assert SECRET not in str(timeline)
    assert SECRET not in str(ana.get(f"/api/refs/asset:{asset}/backlinks").json())
    assert SECRET not in str(ana.get(f"/api/assets/{asset}").json())
    assert SECRET not in str(ana.get(f"/api/assets/{asset}/situation").json())
    # API v1's events, what the assistant's recent_events and the MCP server read.
    assert SECRET not in str(signed.get("/api/v1/events", headers=_token(signed, "ana")).json())

    # Its group and the administrators still read it everywhere.
    for client, username in ((eva, "eva"), (signed, "admin")):
        assert SECRET in client.get("/api/refs", params={"ref": ref}).json()[ref]["title"]
        assert SECRET in str(client.get(f"/api/refs/{ref}/timeline").json())
        events = signed.get("/api/v1/events", headers=_token(signed, username)).json()
        assert SECRET in str(events)


def test_a_message_naming_an_action_shows_its_title_only_to_who_sees_it(signed):  # noqa: F811
    eva = _person(signed, "eva")
    ana = _person(signed, "ana", "viewer")
    action_id = _lab_action(signed, eva)
    response = eva.post(
        "/api/messages/conversations",
        json={"members": ["ana"], "text": f"Look at #action:{action_id}"},
    )
    assert response.status_code == 201, response.text
    conversation = response.json()["conversation"]["conversation_id"]
    path = f"/api/messages/conversations/{conversation}"
    assert SECRET not in str(ana.get(path).json()["messages"])
    assert SECRET in str(eva.get(path).json()["messages"])


def test_a_specialist_answers_with_what_the_person_may_read(signed):  # noqa: F811
    eva = _person(signed, "eva")
    _person(signed, "ana", "viewer")
    rt = signed.app.state.runtime
    # Ana opens only View: Link's results are not hers to read.
    rt.workspace.users.set_access("ana", "viewer", ["dashcraft"])
    ana = TestClient(signed.app)
    assert ana.post("/api/login", json={"username": "ana", "password": PASSWORD}).status_code == 200
    _lab_action(signed, eva)
    _specialist(signed, apps=["linkcraft"])
    asset = _asset_id(signed)
    _publish_result(signed, f"asset:{asset}")

    _id, messages = _talk(ana, f"E a #asset:{asset}?")
    assert "Valve stiction suspected" not in messages[-1]["text"]
    _id, messages = _talk(ana, "o que precisa de atenção?")
    assert "Valve stiction suspected" not in messages[-1]["text"]
    _id, messages = _talk(ana, "quais ações estão abertas?")
    assert SECRET not in str(messages[-1])
    assert "action:" not in messages[-1]["text"]

    # Someone who opens Link and is in the lab reads both.
    _id, messages = _talk(signed, f"E a #asset:{asset}?")
    assert "Valve stiction suspected" in messages[-1]["text"]
    _id, messages = _talk(eva, "quais ações estão abertas?")
    assert SECRET in str(messages[-1])


def test_in_a_group_a_specialist_reads_what_everyone_there_may_read(signed):  # noqa: F811
    eva = _person(signed, "eva")
    _person(signed, "ana", "viewer")
    _lab_action(signed, eva)
    _specialist(signed)
    response = eva.post(
        "/api/messages/conversations",
        json={"members": ["ana", "malhas"], "title": "Turno", "text": "@malhas ações abertas?"},
    )
    assert response.status_code == 201, response.text
    signed.app.state.runtime.specialist_chat.drain(timeout=10)
    conversation = response.json()["conversation"]["conversation_id"]
    thread = eva.get(f"/api/messages/conversations/{conversation}").json()
    assert thread["messages"][-1]["author"] == "malhas"
    # Ana is in the conversation and does not see the lab's action: nobody there reads it.
    assert SECRET not in str(thread["messages"][-1])


def test_what_an_app_publishes_is_read_only_by_who_may_open_it(signed):  # noqa: F811
    """One rule (review decision D1): the results, events and runs of an app reach a person
    only when they may open it, through API v1, the asset's page and Desk alike."""

    _person(signed, "ana", "viewer")
    rt = signed.app.state.runtime
    rt.workspace.users.set_access("ana", "viewer", ["dashcraft"])
    ana = TestClient(signed.app)
    assert ana.post("/api/login", json={"username": "ana", "password": PASSWORD}).status_code == 200
    asset = _asset_id(signed)
    ref = f"asset:{asset}"
    _publish_result(signed, ref)
    rt.workspace.events.publish(
        "linkcraft.loop.degraded", ref, source="linkcraft", summary="Valve stiction suspected"
    )
    rt.workspace.results.put_runs(
        [
            {
                "app": "linkcraft", "id": "r1", "name": "Valve stiction suspected",
                "status": "done", "trigger": "manual", "started_at": None, "finished_at": None,
                "subjects": [ref], "summary": "", "url": None, "by": None, "progress": None,
                "step": None, "cancel": None,
            }
        ],
        now="2026-10-27T00:00:00Z",
        cutoff="2026-01-01T00:00:00Z",
    )  # fmt: skip

    def read(headers: dict[str, str]) -> str:
        return str(
            [
                signed.get(path, params={"subject": ref, "ref": ref}, headers=headers).json()
                for path in ("/api/v1/results", "/api/v1/events", "/api/v1/runs")
            ]
            + [
                signed.get(
                    "/api/v1/results/history", params={"subject": ref}, headers=headers
                ).json()
            ]
        )

    assert "Valve stiction suspected" not in read(_token(signed, "ana"))
    assert "Valve stiction suspected" not in str(ana.get(f"/api/assets/{asset}/situation").json())
    assert "Valve stiction suspected" not in str(ana.get(f"/api/assets/{asset}").json())
    # Who opens Analytics, and the administrator, read all of it.
    assert read(_token(signed, "admin")).count("Valve stiction suspected") >= 3
    assert "Valve stiction suspected" in str(signed.get(f"/api/assets/{asset}/situation").json())


def test_a_link_to_an_apps_item_names_it_only_to_who_opens_the_app(signed):  # noqa: F811
    """``#run:linkcraft/7`` or an app's text: its title stays with who may open the app."""

    _person(signed, "ana", "viewer")
    rt = signed.app.state.runtime
    rt.workspace.users.set_access("ana", "viewer", ["dashcraft"])
    rt.workspace.results.put_runs(
        [
            {
                "app": "linkcraft", "id": "7", "name": "Valve stiction suspected",
                "status": "done", "trigger": "manual", "started_at": None, "finished_at": None,
                "subjects": [], "summary": "", "url": "/link/runs/7", "by": None,
                "progress": None, "step": None, "cancel": None,
            }
        ],
        now="2026-10-27T00:00:00Z",
        cutoff="2026-01-01T00:00:00Z",
    )  # fmt: skip
    refs = rt.platform.refs
    hidden = refs.resolve("run:linkcraft/7", viewer="ana")
    assert hidden["hidden"] is True and hidden["href"] is None
    assert SECRET not in str(hidden) and "Valve" not in hidden["title"]
    assert refs.resolve("run:linkcraft/7", viewer="admin")["title"] == "Valve stiction suspected"


def test_a_write_from_another_site_with_the_session_cookie_is_refused(signed):  # noqa: F811
    """Review S1: SameSite=Lax lets a sibling server of the company's domain post with the
    cookie; the browser's Sec-Fetch-Site tells the request apart."""

    body = {"name": "Night shift", "members": []}
    other = signed.post("/api/groups", json=body, headers={"Sec-Fetch-Site": "same-site"})
    assert other.status_code == 403
    assert signed.post("/api/groups", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403  # fmt: skip
    assert signed.get("/api/groups", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
    mine = signed.post("/api/groups", json=body, headers={"Sec-Fetch-Site": "same-origin"})
    assert mine.status_code == 201
    # A script with its own token is not a browser riding a cookie.
    token = _token(signed, "admin") | {"Sec-Fetch-Site": "cross-site"}
    event = {"kind": "note", "subject": "app:processcraft", "app": "linkcraft"}
    assert signed.post("/api/v1/events", json=event, headers=token).status_code != 403
