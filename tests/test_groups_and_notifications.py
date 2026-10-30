# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""Groups of people and the notifications apps send them (docs/groups.md, docs/notifications.md)."""

from __future__ import annotations

from datetime import datetime, timezone

import plantcraft.notify as notify
from tests.test_collaboration import _person, signed  # noqa: F401


def _group(client, **changes):
    body = {"name": "Unit 100 operations", "kind": "area", "members": ["ana"], **changes}
    response = client.post("/api/groups", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _service(client, app_id: str = "cpmcraft") -> dict[str, str]:
    key = client.post("/api/app-keys", json={"app_id": app_id, "label": "test"})
    assert key.status_code == 201, key.text
    grant = client.post(
        "/api/v1/auth/service-token", json={"app": app_id, "key": key.json()["key"]}
    )
    assert grant.status_code == 200, grant.text
    return {"Authorization": f"Bearer {grant.json()['token']}"}


def test_admins_keep_groups_and_profiles_show_them(signed):
    ana = _person(signed, "ana")
    _person(signed, "rui")
    group = _group(signed, coordinator="rui", description="Day and night shifts")
    assert group["group_id"] == "unit-100-operations"
    assert [member["username"] for member in group["members"]] == ["ana", "rui"]
    assert group["kind_label"] == "Area" and group["coordinator_name"] == "Rui"
    # The same id twice, an unknown person or kind: refused, nothing written.
    assert signed.post("/api/groups", json={"name": "Unit 100 operations"}).status_code == 409
    assert signed.post("/api/groups", json={"name": "X", "members": ["ghost"]}).status_code == 422
    assert signed.post("/api/groups", json={"name": "X", "kind": "club"}).status_code == 422
    card = ana.get("/api/people/ana").json()
    assert card["groups"] == [
        {
            "group_id": "unit-100-operations",
            "name": "Unit 100 operations",
            "kind": "area",
            "kind_label": "Area",
            "coordinator": False,
            "parent_id": None,
        }
    ]
    # Everyone reads the groups; only administrators create them.
    assert ana.get("/api/groups").json()["groups"][0]["name"] == "Unit 100 operations"
    assert ana.post("/api/groups", json={"name": "Mine"}).status_code == 403


def test_the_coordinator_changes_the_members_and_nobody_else(signed):
    ana = _person(signed, "ana")
    rui = _person(signed, "rui", level="viewer")
    _person(signed, "eva")
    _group(signed, coordinator="rui")
    path = "/api/groups/unit-100-operations/members"
    assert ana.put(path, json={"members": ["ana", "eva"]}).status_code == 403
    changed = rui.put(path, json={"members": ["eva"]})
    assert changed.status_code == 200, changed.text
    # The coordinator always stays a member.
    assert [member["username"] for member in changed.json()["members"]] == ["eva", "rui"]
    assert rui.get("/api/groups/unit-100-operations").json()["can_edit_members"] is True
    assert signed.delete("/api/groups/unit-100-operations").status_code == 200
    assert signed.get("/api/groups/unit-100-operations").status_code == 404
    actions = {entry["action"] for entry in signed.app.state.runtime.workspace.audit.list()}
    assert {"group.created", "group.members", "group.deleted"} <= actions


def test_groups_form_a_tree_and_a_leader_sees_below(signed):
    """groups have a hierarchy; a person may be in several groups."""

    for name in ("boss", "lead", "ana", "eva"):
        _person(signed, name)
    _group(signed, name="Operations", kind="department", coordinator="boss", members=[])
    _group(signed, name="U-100", coordinator="lead", members=["ana"], parent_id="operations")
    _group(signed, name="Shift A", kind="team", members=["eva"], parent_id="u-100")
    _group(signed, name="Lab", kind="discipline", members=["eva"])
    listed = {item["group_id"]: item for item in signed.get("/api/groups").json()["groups"]}
    assert listed["u-100"]["parent_name"] == "Operations"
    assert listed["operations"]["children"] == ["u-100"]
    page = signed.get("/api/groups/shift-a").json()
    assert [item["group_id"] for item in page["path"]] == ["operations", "u-100"]
    assert signed.get("/api/groups/u-100").json()["subgroups"] == [
        {"group_id": "shift-a", "name": "Shift A"}
    ]
    # A loop in the tree, or an unknown parent: refused.
    body = {"name": "Operations", "kind": "department", "coordinator": "boss", "members": []}
    assert (
        signed.put("/api/groups/operations", json={**body, "parent_id": "shift-a"}).status_code
        == 422
    )
    assert signed.post("/api/groups", json={"name": "Y", "parent_id": "nope"}).status_code == 422
    groups = signed.app.state.runtime.workspace.groups
    boss = groups.scope("boss")
    assert boss["groups"] == {"operations", "u-100", "shift-a"}
    assert boss["people"] == {"boss", "lead", "ana", "eva"}
    assert groups.scope("lead")["people"] == {"lead", "ana", "eva"}
    assert groups.scope("eva") == {"groups": {"shift-a", "lab"}, "people": {"eva"}, "led": set()}
    # Users › edit: the groups a person is in, several at once.
    accounts = signed.get("/api/users/accounts").json()
    eva = next(item for item in accounts["users"] if item["username"] == "eva")
    assert sorted(eva["groups"]) == ["lab", "shift-a"]
    assert {"group_id": "lab", "name": "Lab", "kind_label": "Discipline"} in accounts["groups"]
    changed = signed.put(
        "/api/users/eva",
        json={"display_name": "Eva", "access_level": "editor", "groups": ["lab", "u-100"]},
    )
    assert changed.status_code == 200, changed.text
    assert sorted(changed.json()["groups"]) == ["lab", "u-100"]
    # A leader stays in the group they lead; an unknown group is refused.
    signed.put(
        "/api/users/lead", json={"display_name": "Lead", "access_level": "editor", "groups": []}
    )
    assert "u-100" in [item["group_id"] for item in groups.of("lead")]
    bad = {"display_name": "Eva", "access_level": "editor", "groups": ["ghost"]}
    assert signed.put("/api/users/eva", json=bad).status_code == 422
    # Deleting a group moves the ones under it up.
    signed.delete("/api/groups/u-100")
    assert signed.get("/api/groups/shift-a").json()["parent_id"] == "operations"


def test_an_app_notifies_a_group_in_messages(signed):
    ana = _person(signed, "ana")
    _person(signed, "rui")
    _group(signed, members=["ana", "rui"])
    headers = _service(signed)
    people = signed.get("/api/v1/people", headers=headers).json()
    assert {"username", "name", "role", "job_title", "unit", "groups"} <= set(people[0])
    assert "email" not in people[0]
    assert signed.get("/api/v1/groups", headers=headers).json()[0]["members"] == ["ana", "rui"]
    body = {
        "recipients": ["group:unit-100-operations", "user:ana", "user:ghost"],
        "title": "FIC-1003 flow below 40 m3/h",
        "text": "Since 10:02. Check the feed pump.",
        "priority": "high",
        "url": "/cpm/loops/FIC-1003",
        "key": "alarm:12",
    }
    # No email server set up: an app does not offer email.
    assert signed.get("/api/v1/notifications", headers=headers).json() == {"email": False}
    answer = signed.post("/api/v1/notifications", json=body, headers=headers)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {
        "delivered": ["ana", "rui"],
        "email_queued": 0,
        "unknown": ["user:ghost"],
    }
    # Messages counts it among the notifications, apart from the chats.
    counts = ana.get("/api/v1/inbox").json()
    assert (counts["unread_messages"], counts["unread_notifications"]) == (0, 1)
    items = ana.get("/api/messages/conversations").json()["items"]
    thread = ana.get(f"/api/messages/conversations/{items[0]['conversation_id']}").json()
    message = thread["messages"][-1]
    assert message["text"].startswith("**FIC-1003 flow below 40 m3/h**")
    assert message["meta"]["kind"] == "notification" and message["meta"]["url"] == body["url"]
    # A second notification lands in the same conversation.
    signed.post("/api/v1/notifications", json={**body, "recipients": ["user:ana"]}, headers=headers)
    assert len(ana.get("/api/messages/conversations").json()["items"]) == 1
    # A person's token, a link to another site, no recipient: refused.
    person = signed.post("/api/v1/notifications", json=body)
    assert person.status_code in {401, 403}
    away = {**body, "url": "https://example.com"}
    assert signed.post("/api/v1/notifications", json=away, headers=headers).status_code == 422
    empty = {**body, "recipients": []}
    assert signed.post("/api/v1/notifications", json=empty, headers=headers).status_code == 422


def test_email_goes_out_by_preference_and_in_one_digest(signed, monkeypatch):
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        notify,
        "send_mail",
        lambda settings, password, to, subject, body: sent.append((to, subject, body)),
    )
    _person(signed, "ana")
    rui = _person(signed, "rui")
    rt = signed.app.state.runtime
    rt.workspace.users.set_profile("ana", {"email": "ana@example.com"})
    rt.workspace.users.set_profile("rui", {"email": "rui@example.com"})
    settings = signed.put(
        "/api/mail",
        json={
            "enabled": True,
            "host": "smtp.plant.local",
            "sender": "suite@plant.local",
            "password": "s3cret",
        },
    )
    assert settings.status_code == 200, settings.text
    assert settings.json()["has_password"] and "password" not in settings.json()
    assert rui.put("/api/me/notifications", json={"email": False}).json()["email"] is False
    headers = _service(signed)
    assert signed.get("/api/v1/notifications", headers=headers).json() == {"email": True}
    base = {"recipients": ["user:ana", "user:rui"], "email": True}
    for title, priority in (("Low one", "low"), ("High one", "high"), ("Critical one", "critical")):
        signed.post(
            "/api/v1/notifications",
            json={**base, "title": title, "priority": priority},
            headers=headers,
        )
    # Ana gets high and above (the default), Rui asked for none: two emails waiting, one digest.
    assert rt.notifications.flush(now=datetime.now(timezone.utc)) == {"sent": 2, "waiting": 0}
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == "ana@example.com" and subject == "2 notifications from PlantCraft"
    assert body.index("[Critical] Critical one") < body.index("[High] High one")
    assert signed.get("/api/mail").json()["outbox"]["sent"] == 2


def test_a_failing_server_keeps_the_email_waiting(signed, monkeypatch):
    def down(*_args):
        raise OSError("connection refused")

    monkeypatch.setattr(notify, "send_mail", down)
    _person(signed, "ana")
    rt = signed.app.state.runtime
    rt.workspace.users.set_profile("ana", {"email": "ana@example.com"})
    signed.put("/api/mail", json={"enabled": True, "host": "smtp", "sender": "a@b.local"})
    body = {"recipients": ["user:ana"], "title": "T", "priority": "critical", "email": True}
    signed.post("/api/v1/notifications", json=body, headers=_service(signed))
    assert rt.notifications.flush() == {"sent": 0, "waiting": 1}
    outbox = signed.get("/api/mail").json()["outbox"]
    assert outbox["pending"] == 1 and "connection refused" in outbox["last_error"]
    # The test email answers with the server's words instead of failing.
    tested = signed.post("/api/mail/test", json={"to": "ana@example.com"}).json()
    assert tested["sent"] is False and "connection refused" in tested["error"]


def test_mail_settings_are_checked(signed):
    assert signed.put("/api/mail", json={"enabled": True}).status_code == 422
    assert signed.put("/api/mail", json={"host": "a b"}).status_code == 422
    assert signed.put("/api/mail", json={"sender": "not-an-address"}).status_code == 422
    assert signed.get("/api/mail").json()["enabled"] is False


class _Server:
    """smtplib.SMTP as the outbox sees it; keeps what was sent."""

    sent: list = []

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def starttls(self, **_kwargs):
        pass

    def send_message(self, message):
        _Server.sent.append(message)


def test_a_line_break_in_an_address_or_title_never_stops_the_outbox(signed, monkeypatch):
    # Security audit 2026-10-22: a person's own profile could hold "a@b.c\nX-A:1". The email
    # header refused it with a ValueError the outbox did not expect, so every flush stopped at
    # that person and nobody after them got an email again.
    ana = _person(signed, "ana")
    _person(signed, "rui")
    refused = ana.put(
        "/api/me/profile",
        json={"display_name": "Ana", "profile": {"email": "ana@example.com\nX-A:1"}},
    )
    assert refused.status_code == 422, refused.text
    for address in ("ana@example.com, x@evil.test", "<ana@example.com>", "ana@example"):
        body = {"display_name": "Ana", "profile": {"email": address}}
        assert ana.put("/api/me/profile", json=body).status_code == 422, address
    assert signed.post("/api/mail/test", json={"to": "a@b.c\nBcc: x@evil.test"}).status_code == 422
    assert signed.put("/api/mail", json={"sender": "a@b.c\nBcc: x@evil.test"}).status_code == 422

    _Server.sent = []
    monkeypatch.setattr(notify.smtplib, "SMTP", _Server)
    rt = signed.app.state.runtime
    rt.workspace.users.set_profile("rui", {"email": "rui@example.com"})
    signed.put("/api/mail", json={"enabled": True, "host": "smtp", "sender": "suite@plant.local"})
    body = {
        "recipients": ["user:ana", "user:rui"],
        "title": "FIC-1003 low\nBcc: x@evil.test",
        "priority": "critical",
        "email": True,
    }
    rt.workspace.users.set_profile("ana", {"email": "ana@example.com"})
    signed.post("/api/v1/notifications", json=body, headers=_service(signed))
    # An address stored before this check existed: written straight into the outbox.
    with rt.notifications.store._connect() as connection:
        connection.execute(
            "UPDATE notification_outbox SET address = ? WHERE username = 'ana'",
            ("ana@example.com\nBcc: x@evil.test",),
        )
    assert rt.notifications.flush() == {"sent": 1, "waiting": 0}
    assert [message["To"] for message in _Server.sent] == ["rui@example.com"]
    assert _Server.sent[0]["Subject"] == "[Critical] FIC-1003 low Bcc: x@evil.test"
    assert _Server.sent[0]["Bcc"] is None
    outbox = signed.get("/api/mail").json()["outbox"]
    assert outbox["failed"] == 1 and "not a valid email address" in outbox["last_error"]
    # Nothing is left to stop the next flush.
    assert rt.notifications.flush() == {"sent": 0, "waiting": 0}


def test_the_smtp_password_never_goes_to_a_server_it_was_not_typed_for(signed):
    # Security audit 2026-10-22: a new server address kept the saved password, so the test email
    # would hand it to whatever server the address named.
    saved = {"enabled": True, "host": "smtp.plant.local", "sender": "s@plant.local"}
    assert signed.put("/api/mail", json={**saved, "password": "s3cret"}).status_code == 200
    assert signed.put("/api/mail", json=saved).status_code == 200
    for change in ({"host": "smtp.rogue.test"}, {"port": 2525}, {"username": "other"}):
        reply = signed.put("/api/mail", json={**saved, **change})
        assert reply.status_code == 422, change
        assert "type the password again" in reply.json()["detail"]
    moved = {**saved, "host": "smtp2.plant.local", "password": "s3cret"}
    assert signed.put("/api/mail", json=moved).status_code == 200


def test_a_group_has_its_own_conversation_that_follows_its_members(signed):
    """chats with a group, and choosing a group when starting one."""

    ana, rui = _person(signed, "ana"), _person(signed, "rui")
    eva = _person(signed, "eva")
    _group(signed, members=["ana", "rui"])
    contacts = ana.get("/api/messages/contacts").json()
    group = next(item for item in contacts["groups"] if item["group_id"] == "unit-100-operations")
    assert group["members"] == ["rui"] and group["mine"] is True
    # Only members open it; the second time is the same conversation.
    assert eva.post("/api/messages/groups/unit-100-operations").status_code == 403
    opened = ana.post("/api/messages/groups/unit-100-operations")
    assert opened.status_code == 200, opened.text
    conversation = opened.json()
    assert conversation["group_id"] == "unit-100-operations" and conversation["is_group"]
    assert conversation["display_title"] == "Unit 100 operations"
    again = rui.post("/api/messages/groups/unit-100-operations").json()
    assert again["conversation_id"] == conversation["conversation_id"]
    path = f"/api/messages/conversations/{conversation['conversation_id']}"
    assert ana.post(f"{path}/messages", json={"text": "Shift handover at 7"}).status_code == 201
    # Eva joins the group: the conversation is in her list, its history already read.
    body = {"display_name": "Eva", "access_level": "editor", "groups": ["unit-100-operations"]}
    assert signed.put("/api/users/eva", json=body).status_code == 200
    listed = eva.get("/api/messages/conversations").json()
    assert [item["conversation_id"] for item in listed["items"]] == [
        conversation["conversation_id"]
    ]
    assert listed["unread"] == 0
    # People are added through the group, not the conversation.
    assert ana.post(f"{path}/members", json={"members": ["eva"]}).status_code == 422
    # Rui leaves the group: he no longer reads or writes there.
    signed.put("/api/groups/unit-100-operations/members", json={"members": ["ana", "eva"]})
    assert rui.get(path).status_code == 403
    assert rui.get("/api/messages/conversations").json()["items"] == []
    # The group is deleted: the conversation stays with the people in it.
    signed.delete("/api/groups/unit-100-operations")
    kept = ana.get(path).json()["conversation"]
    assert kept["group_id"] is None and kept["title"] == "Unit 100 operations"


def test_notifications_read_like_an_inbox_one_thread_per_key(signed):
    ana = _person(signed, "ana")
    headers = _service(signed)
    body = {
        "recipients": ["user:ana"],
        "title": "FIC-1003 HI",
        "text": "Above 80 %.",
        "priority": "high",
        "url": "/cpm/loops/FIC-1003",
        "key": "alarm:12:1",
        "category": "alarm",
        "actions": [{"label": "Acknowledge", "href": "/alarm/alarms/12"}],
    }
    assert signed.post("/api/v1/notifications", json=body, headers=headers).status_code == 200
    reminder = {**body, "title": "FIC-1003 HI, still active", "priority": "critical"}
    assert signed.post("/api/v1/notifications", json=reminder, headers=headers).status_code == 200
    other = {**body, "key": "alarm:13:1", "title": "TIC-2 LO", "category": None, "actions": []}
    assert signed.post("/api/v1/notifications", json=other, headers=headers).status_code == 200
    feed = ana.get("/api/notifications").json()
    threads = [item for item in feed["items"] if item["kind"] == "notice"]
    assert [item["title"] for item in threads] == ["TIC-2 LO", "FIC-1003 HI, still active"]
    fic = threads[1]
    assert fic["state"] == "unread" and fic["category"] == "alarm" and fic["priority"] == "critical"
    assert fic["actions"] == [{"label": "Acknowledge", "href": "/alarm/alarms/12", "method": "GET"}]
    assert [step["title"] for step in fic["history"]] == [
        "FIC-1003 HI, still active",
        "FIC-1003 HI",
    ]
    assert fic["href"] == "/cpm/loops/FIC-1003" and threads[0]["category"] == "info"
    assert feed["counts"]["unread"] == 2
    # Read, then archived; a new event brings the thread back as unread.
    marked = ana.post("/api/notifications/marks", json={"keys": [fic["key"]], "state": "read"})
    assert marked.status_code == 200
    assert ana.get("/api/v1/inbox").json()["unread_notifications"] == 1
    ana.post("/api/notifications/marks", json={"keys": [fic["key"]], "state": "archived"})
    states = {item["key"]: item["state"] for item in ana.get("/api/notifications").json()["items"]}
    assert states[fic["key"]] == "archived"
    cleared = {**body, "title": "FIC-1003 back to normal", "priority": "low"}
    signed.post("/api/v1/notifications", json=cleared, headers=headers)
    again = [
        item for item in ana.get("/api/notifications").json()["items"] if item["kind"] == "notice"
    ]
    assert again[0]["title"] == "FIC-1003 back to normal" and again[0]["state"] == "unread"
    # Buttons are paths of the suite; a category is one of four.
    away = {**body, "actions": [{"label": "Go", "href": "https://example.com"}]}
    assert signed.post("/api/v1/notifications", json=away, headers=headers).status_code == 422
    odd = {**body, "category": "news"}
    assert signed.post("/api/v1/notifications", json=odd, headers=headers).status_code == 422


def test_a_notification_carries_its_category_and_buttons(signed):
    ana = _person(signed, "ana")
    headers = _service(signed)
    body = {
        "recipients": ["user:ana"],
        "title": "FIC-1003 HI",
        "text": "Above 80 %.",
        "key": "alarm:12:1",
        "category": "alarm",
        "actions": [{"label": "Acknowledge", "href": "/alarm/alarms/12"}],
    }
    assert signed.post("/api/v1/notifications", json=body, headers=headers).status_code == 200
    items = ana.get("/api/messages/conversations").json()["items"]
    thread = ana.get(f"/api/messages/conversations/{items[0]['conversation_id']}").json()
    meta = thread["messages"][-1]["meta"]
    assert meta["category"] == "alarm" and meta["key"] == "alarm:12:1"
    assert meta["actions"] == [
        {"label": "Acknowledge", "href": "/alarm/alarms/12", "method": "GET"}
    ]
    # Buttons are paths of the suite, at most three; a category is one of four.
    away = {**body, "actions": [{"label": "Go", "href": "https://example.com"}]}
    assert signed.post("/api/v1/notifications", json=away, headers=headers).status_code == 422
    many = {**body, "actions": [{"label": str(n), "href": "/a"} for n in range(4)]}
    assert signed.post("/api/v1/notifications", json=many, headers=headers).status_code == 422
    odd = {**body, "category": "news"}
    assert signed.post("/api/v1/notifications", json=odd, headers=headers).status_code == 422
