# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""What apps send to the sidebar's quick buttons (docs/quick-access.md): notifications whose
buttons run a call in the app, settled for everyone by key, the urgent pop-up, and the runs the
Queue lists, with who started them and the notice when they end."""

from __future__ import annotations

import pytest

from tests.test_collaboration import _person, signed  # noqa: F401
from tests.test_groups_and_notifications import _service


@pytest.fixture
def alarms(signed, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_APPS", "alarmcraft=/alarm/,linkcraft=/link/")
    return _service(signed, "alarmcraft")


def _alarm(**changes):
    return {
        "recipients": ["user:ana", "user:rui"],
        "title": "FIC-1003 flow low",
        "priority": "critical",
        "url": "/alarm/alarms/12",
        "key": "alarm:12:1",
        "category": "alarm",
        "actions": [
            {"label": "Acknowledge", "href": "/alarm/api/alarms/12/ack", "method": "POST"},
            {"label": "Open the rule", "href": "/alarm/rules/4"},
        ],
        **changes,
    }


def _notice(client, key="alarm:12:1"):
    items = client.get("/api/notifications").json()["items"]
    return next(item for item in items if item["kind"] == "notice" and f":{key}:" in item["key"])


def test_a_button_runs_a_call_only_in_the_app_that_sent_it(signed, alarms):
    ana = _person(signed, "ana")
    _person(signed, "rui")
    sent = signed.post("/api/v1/notifications", json=_alarm(), headers=alarms)
    assert sent.status_code == 200, sent.text
    notice = _notice(ana)
    assert notice["actions"] == [
        {"label": "Acknowledge", "href": "/alarm/api/alarms/12/ack", "method": "POST"},
        {"label": "Open the rule", "href": "/alarm/rules/4", "method": "GET"},
    ]
    assert notice["resolved"] is None
    # A call into another app, or out of the prefix, is refused: a notification never makes a
    # person act somewhere else.
    for href in ("/link/api/runs/1/cancel", "/alarmcraft/x", "/alarm/../link/api/x"):
        body = _alarm(actions=[{"label": "Do", "href": href, "method": "POST"}])
        assert signed.post("/api/v1/notifications", json=body, headers=alarms).status_code == 422
    odd = _alarm(actions=[{"label": "Do", "href": "/alarm/x", "method": "DELETE"}])
    assert signed.post("/api/v1/notifications", json=odd, headers=alarms).status_code == 422


def test_the_app_settles_a_notification_for_everyone(signed, alarms):
    ana = _person(signed, "ana")
    rui = _person(signed, "rui")
    signed.post("/api/v1/notifications", json=_alarm(), headers=alarms)
    assert ana.get("/api/v1/inbox").json()["unread_notifications"] == 1
    # Only an app settles what it sent.
    assert ana.post("/api/v1/notifications/resolve", json={"key": "alarm:12:1"}).status_code == 403
    done = signed.post(
        "/api/v1/notifications/resolve",
        json={"key": "alarm:12:1", "note": "Acknowledged by Ana"},
        headers=alarms,
    )
    assert done.status_code == 200, done.text
    assert done.json()["note"] == "Acknowledged by Ana"
    for person in (ana, rui):
        notice = _notice(person)
        assert notice["state"] == "read" and notice["actions"] == []
        assert notice["resolved"]["note"] == "Acknowledged by Ana"
        assert person.get("/api/v1/inbox").json()["unread_notifications"] == 0
    # Settling again is harmless; another app's key of the same name is not touched.
    again = {"key": "alarm:12:1", "note": "Acknowledged by Ana"}
    assert (
        signed.post("/api/v1/notifications/resolve", json=again, headers=alarms).status_code == 200
    )
    # A new send under the same key opens it again, buttons back.
    signed.post("/api/v1/notifications", json=_alarm(title="FIC-1003 again"), headers=alarms)
    reopened = _notice(rui)
    assert reopened["state"] == "unread" and reopened["resolved"] is None
    assert len(reopened["actions"]) == 2


def test_a_critical_notification_pops_up_with_its_buttons(signed, alarms):
    ana = _person(signed, "ana")
    _person(signed, "rui")
    low = _alarm(key="alarm:9:1", priority="low", title="Low one")
    signed.post("/api/v1/notifications", json=low, headers=alarms)
    assert ana.get("/api/v1/inbox").json()["urgent_notification"] is None
    signed.post("/api/v1/notifications", json=_alarm(), headers=alarms)
    urgent = ana.get("/api/v1/inbox").json()["urgent_notification"]
    assert urgent["title"] == "FIC-1003 flow low" and urgent["priority"] == "critical"
    assert urgent["actions"][0]["method"] == "POST"
    # Read or settled: it no longer pops up.
    ana.post("/api/notifications/marks", json={"keys": [urgent["key"]], "state": "read"})
    assert ana.get("/api/v1/inbox").json()["urgent_notification"] is None


def _run(**changes):
    run_id = changes.get("id", "r-1")
    return {
        "id": run_id,
        "name": "Loop health, area 200",
        "status": "running",
        "trigger": "manual",
        "started_at": "2026-10-26T10:00:00Z",
        "url": f"/link/runs/{run_id}",
        "by": "ana",
        "progress": 0.4,
        "step": "Reading 40 of 100 loops",
        "cancel": f"/link/api/runs/{run_id}/cancel",
        **changes,
    }


def test_runs_say_who_started_them_how_far_they_went_and_how_to_cancel(signed, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_APPS", "alarmcraft=/alarm/,linkcraft=/link/")
    link = _service(signed, "linkcraft")
    _person(signed, "ana")
    saved = signed.put("/api/v1/runs", json=[_run()], headers=link)
    assert saved.json() == {"saved": 1, "errors": []}
    run = signed.get("/api/v1/runs", params={"by": "ana"}, headers=link).json()[0]
    assert (run["by"], run["progress"], run["step"]) == ("ana", 0.4, "Reading 40 of 100 loops")
    assert run["cancel"] == "/link/api/runs/r-1/cancel"
    assert signed.get("/api/v1/runs", params={"by": "rui"}, headers=link).json() == []
    # Cancel is a path of the app itself; progress is 0 to 1.
    bad = signed.put(
        "/api/v1/runs", json=[_run(id="r-2", cancel="/alarm/api/x")], headers=link
    ).json()
    assert bad["saved"] == 0 and bad["errors"][0]["status"] == 422
    assert signed.put("/api/v1/runs", json=[_run(progress=1.5)], headers=link).status_code == 422


def test_the_platform_tells_the_person_who_started_a_run_when_it_ends(signed, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_APPS", "alarmcraft=/alarm/,linkcraft=/link/")
    link = _service(signed, "linkcraft")
    ana = _person(signed, "ana")

    def notices():
        items = ana.get("/api/notifications").json()["items"]
        return [item for item in items if item["kind"] == "notice"]

    signed.put("/api/v1/runs", json=[_run()], headers=link)
    # Done in 30 s: the Queue button turns green, no notification.
    quick = _run(status="done", progress=1, finished_at="2026-10-26T10:00:30Z")
    signed.put("/api/v1/runs", json=[quick], headers=link)
    assert notices() == []
    # Done after five minutes: one notice; written again, still one.
    signed.put("/api/v1/runs", json=[_run(id="r-3")], headers=link)
    slow = _run(id="r-3", status="done", finished_at="2026-10-26T10:05:00Z")
    signed.put("/api/v1/runs", json=[slow], headers=link)
    signed.put("/api/v1/runs", json=[slow], headers=link)
    found = notices()
    assert [item["title"] for item in found] == ["Done: Loop health, area 200"]
    assert found[0]["category"] == "run" and found[0]["href"] == "/link/runs/r-3"
    # Failed: always, and high.
    signed.put("/api/v1/runs", json=[_run(id="r-4")], headers=link)
    failed = _run(id="r-4", status="failed", summary="Source down")
    signed.put("/api/v1/runs", json=[failed], headers=link)
    top = notices()[0]
    assert top["title"] == "Failed: Loop health, area 200" and top["priority"] == "high"
    assert top["detail"] == "Source down"
    # A scheduled run nobody started tells nobody.
    nobody = _run(id="r-5", status="failed", by=None, trigger="schedule")
    signed.put("/api/v1/runs", json=[nobody], headers=link)
    assert len(notices()) == 2


def test_the_queue_panel_lists_mine_and_what_runs_now(signed, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_APPS", "alarmcraft=/alarm/,linkcraft=/link/")
    link = _service(signed, "linkcraft")
    ana = _person(signed, "ana")
    runs = [
        _run(),
        _run(id="r-2", by="rui", status="queued"),
        _run(id="r-3", status="failed", finished_at="2026-10-26T10:01:00Z"),
        _run(id="r-4", by=None, status="done", trigger="schedule"),
    ]
    assert signed.put("/api/v1/runs", json=runs, headers=link).json()["saved"] == 4
    panel = ana.get("/api/v1/queue").json()
    assert panel["me"] == "ana"
    assert {run["id"] for run in panel["mine"]} == {"r-1", "r-3"}
    assert {run["id"] for run in panel["running"]} == {"r-1", "r-2"}
    assert panel["mine"][0]["app_name"]
    # A service token has no panel.
    assert signed.get("/api/v1/queue", headers=link).status_code == 403
