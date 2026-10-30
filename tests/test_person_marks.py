# ruff: noqa: F811  (the fixtures come from test_collaboration.py, test_quick_access.py, test_demo_visits.py)
"""What a person marks for themselves (owner, 2026-10-28): a notification done (the check), seen
or not seen again with one button, a favorite; a conversation or an assistant chat unread again
or a favorite. A public demo visit keeps its own marks: the next visitor starts as seeded."""

from __future__ import annotations

from fastapi.testclient import TestClient

from plantcraft.api.feed import mark_key
from tests.test_collaboration import _person, signed  # noqa: F401
from tests.test_demo_visits import EDGE, demo_app  # noqa: F401
from tests.test_quick_access import _alarm, _notice, alarms  # noqa: F401


def test_a_favorite_keeps_its_star_when_a_new_event_arrives():
    assert mark_key("notice:alarmcraft:alarm:12:1:57") == "notice:alarmcraft:alarm:12:1"
    assert (
        mark_key("action:4:2026-10-28T10:00:00Z:comment") == "action:4:2026-10-28T10:00:00Z:comment"
    )
    assert mark_key("conversation:7") == "conversation:7"


def test_a_notification_is_checked_done_seen_again_and_starred(signed, alarms):
    ana = _person(signed, "ana")
    rui = _person(signed, "rui")
    signed.post("/api/v1/notifications", json=_alarm(), headers=alarms)
    notice = _notice(ana)
    assert notice["state"] == "unread" and notice["starred"] is False
    marks = "/api/notifications/marks"

    # One button, both ways: seen, then not seen again.
    assert ana.post(marks, json={"keys": [notice["key"]], "state": "read"}).status_code == 200
    assert _notice(ana)["state"] == "read"
    assert ana.post(marks, json={"keys": [notice["key"]], "state": None}).status_code == 200
    assert _notice(ana)["state"] == "unread"
    assert ana.get("/api/v1/inbox").json()["unread_notifications"] == 1

    # The star stays on the thread when the app sends again under the same key.
    star = {"key": notice["key"], "mark": "star", "on": True}
    assert ana.put("/api/me/marks", json=star).status_code == 200
    assert _notice(ana)["starred"] is True
    signed.post("/api/v1/notifications", json=_alarm(title="FIC-1003 again"), headers=alarms)
    again = _notice(ana)
    assert again["key"] != notice["key"] and again["starred"] is True

    # The check: done, out of the list until something new happens; and back.
    ana.post(marks, json={"keys": [again["key"]], "state": "archived"})
    assert _notice(ana)["state"] == "archived"
    ana.post(marks, json={"keys": [again["key"]], "state": "read"})
    assert _notice(ana)["state"] == "read"

    # Marks are the person's own: Rui's notification is untouched.
    assert _notice(rui)["state"] == "unread" and _notice(rui)["starred"] is False
    # Only the kinds of keys that exist can be marked; unread only on conversations and chats.
    assert ana.put("/api/me/marks", json={"key": "users:1", "mark": "star"}).status_code == 422
    assert ana.put("/api/me/marks", json={"key": again["key"], "mark": "unread"}).status_code == 422


def test_a_conversation_is_marked_unread_until_it_is_opened_and_starred(signed):
    ana = _person(signed, "ana")
    rui = _person(signed, "rui")
    started = ana.post(
        "/api/messages/conversations", json={"members": ["rui"], "text": "Olá"}
    ).json()
    cid = started["conversation"]["conversation_id"]
    rui.post(f"/api/messages/conversations/{cid}/read")
    listed = rui.get("/api/messages/conversations").json()
    assert listed["unread"] == 0

    key = f"conversation:{cid}"
    assert rui.put("/api/me/marks", json={"key": key, "mark": "unread"}).status_code == 200
    listed = rui.get("/api/messages/conversations").json()
    item = next(entry for entry in listed["items"] if entry["conversation_id"] == cid)
    assert item["unread"] == 1 and item["marked_unread"] is True and listed["unread"] == 1
    assert rui.get("/api/v1/inbox").json()["unread_messages"] == 1
    # Ana's view does not change.
    assert ana.get("/api/messages/conversations").json()["unread"] == 0

    # Opening it reads it.
    assert rui.post(f"/api/messages/conversations/{cid}/read").json()["unread"] == 0
    assert rui.get("/api/v1/inbox").json()["unread_messages"] == 0

    rui.put("/api/me/marks", json={"key": key, "mark": "star"})
    opened = rui.get(f"/api/messages/conversations/{cid}").json()["conversation"]
    assert opened["starred"] is True
    rui.put("/api/me/marks", json={"key": key, "mark": "star", "on": False})
    assert rui.get(f"/api/messages/conversations/{cid}").json()["conversation"]["starred"] is False


def test_an_assistant_chat_is_starred_first_and_unread_until_opened(signed):
    rt = signed.app.state.runtime
    first = rt.assistant.store.create("admin", "Pumps")
    second = rt.assistant.store.create("admin", "Valves")
    key = f"chat:{first['chat_id']}"
    signed.put("/api/me/marks", json={"key": key, "mark": "star"})
    signed.put("/api/me/marks", json={"key": key, "mark": "unread"})
    chats = signed.get("/api/assistant").json()["chats"]
    assert [chat["chat_id"] for chat in chats] == [first["chat_id"], second["chat_id"]]
    assert chats[0]["starred"] is True and chats[0]["unread"] is True
    assert chats[1]["starred"] is False and chats[1]["unread"] is False
    assert signed.get(f"/api/assistant/chats/{first['chat_id']}").json()["chat"]["starred"] is True
    assert signed.get("/api/assistant").json()["chats"][0]["unread"] is False


def test_a_demo_visit_marks_for_itself_only(demo_app):
    rt = demo_app.state.runtime
    sent = rt.workspace.messages
    conversation = sent.start("admin", ["demo"], title="")
    sent.post(conversation["conversation_id"], "admin", "Welcome")
    visitor = TestClient(demo_app, headers=EDGE)
    assert visitor.post("/api/demo/enter", json={}).json()["entered"] is True
    cid = conversation["conversation_id"]
    key = f"conversation:{cid}"
    # A viewer visit may mark, and its marks are the visit's.
    assert visitor.put("/api/me/marks", json={"key": key, "mark": "star"}).status_code == 200
    starred = visitor.get(f"/api/messages/conversations/{cid}").json()["conversation"]["starred"]
    assert starred is True
    assert rt.desk.marks("demo", "star") == set()
    assert (
        visitor.post("/api/notifications/marks", json={"keys": ["action:1:x:y"]}).status_code == 200
    )
    assert rt.desk.triage("demo") == {}
    # A Desk suggestion snoozed or dismissed is the visit's too.
    key = "suggestion:demo:x"
    assert visitor.post("/api/desk/triage", json={"key": key, "state": "done"}).status_code == 200
    assert rt.desk.triage("demo") == {}
    # Still read-only for anything else.
    assert visitor.post("/api/actions", json={"title": "x"}).status_code == 403

    # The next visitor starts from the demo as it was seeded.
    visitor.post("/api/logout")
    other = TestClient(demo_app, headers=EDGE)
    assert other.post("/api/demo/enter", json={}).json()["entered"] is True
    fresh = other.get(f"/api/messages/conversations/{cid}").json()["conversation"]
    assert fresh["starred"] is False


def test_a_demo_visit_reads_a_conversation_for_itself_only(demo_app):
    """Opening a conversation is the visit's read: the next visitor finds it unread as seeded
    (owner, 2026-10-28), and the seed leaves the newest few unread for every visit."""

    from plantcraft.demo_seed import VISITOR_UNREAD, visitor_unread

    rt = demo_app.state.runtime
    sent = rt.workspace.messages
    rt.workspace.users.upsert_user("ana", "Ana", "Engineer")
    ids = []
    for number in range(VISITOR_UNREAD + 2):
        started = sent.start("ana", ["demo"], title=f"Talk {number}")
        sent.post(started["conversation_id"], "ana", "First")
        sent.post(started["conversation_id"], "ana", "Second")
        ids.append(started["conversation_id"])
    assert visitor_unread(rt.workspace) == VISITOR_UNREAD
    assert visitor_unread(rt.workspace) == VISITOR_UNREAD  # the seed again: the same
    assert sent.unread_total("demo") == VISITOR_UNREAD

    visitor = TestClient(demo_app, headers=EDGE)
    assert visitor.post("/api/demo/enter", json={}).json()["entered"] is True
    assert visitor.get("/api/messages/conversations").json()["unread"] == VISITOR_UNREAD
    newest = ids[-1]
    read = visitor.post(f"/api/messages/conversations/{newest}/read", json={})
    assert read.json()["unread"] == VISITOR_UNREAD - 1
    listed = visitor.get("/api/messages/conversations").json()
    assert listed["unread"] == VISITOR_UNREAD - 1
    assert (
        next(item for item in listed["items"] if item["conversation_id"] == newest)["unread"] == 0
    )
    # The account's own read marks are untouched.
    assert sent.unread_total("demo") == VISITOR_UNREAD

    visitor.post("/api/logout")
    other = TestClient(demo_app, headers=EDGE)
    assert other.post("/api/demo/enter", json={}).json()["entered"] is True
    assert other.get("/api/messages/conversations").json()["unread"] == VISITOR_UNREAD


def test_a_demo_visit_starts_with_the_newest_notifications_unread(demo_app):
    from plantcraft.api.feed import DEMO_UNREAD, notification_feed

    rt = demo_app.state.runtime
    robot = rt.workspace.messages
    rt.workspace.users.upsert_user("alarmcraft", "Alarms", "App", kind="system")
    talk = robot.start("alarmcraft", ["demo"], title="")
    for number in range(DEMO_UNREAD + 7):
        robot.post(
            talk["conversation_id"],
            "alarmcraft",
            f"**Alarm {number}**",
            meta={"kind": "notification", "app": "alarmcraft", "key": f"alarm:{number}"},
        )
    everyone = notification_feed(rt, "demo")
    assert sum(item["state"] == "unread" for item in everyone) == DEMO_UNREAD + 7
    visit = notification_feed(rt, "demo", "demo#visit:a")
    unread = [item for item in visit if item["state"] == "unread"]
    assert len(unread) == DEMO_UNREAD and unread[0]["key"] == visit[0]["key"]
    # Marking one read takes one off, it does not bring an older one back.
    rt.desk.set_triage("demo#visit:a", unread[0]["key"], "read")
    again = notification_feed(rt, "demo", "demo#visit:a")
    assert sum(item["state"] == "unread" for item in again) == DEMO_UNREAD - 1
    other = notification_feed(rt, "demo", "demo#visit:b")
    assert sum(item["state"] == "unread" for item in other) == DEMO_UNREAD
