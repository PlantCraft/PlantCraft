"""Responsibles, areas and disciplines; each rule's notifications, gathering, the limit per
person, silences, reminders, hours and escalation, sent through PlantCraft's API v1
notifications (the fake records them)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.conftest import client_for, events_rule, high, make_rule, notify


def _later(fake, minutes: int) -> None:
    """Move the plant's clock on (the series end at the start; no value changes after)."""

    fake._now += timedelta(minutes=minutes)


OPERATIONS = notify(recipients=["group:operations"])


def test_an_alarm_has_a_responsible_an_area_and_a_discipline(client, runtime, fake):
    rule = make_rule(client, high(discipline="process"))
    alarm = client.get(f"/api/alarms/{rule['rule_id']}").json()
    # The creator answers for it unless someone else is named; the area comes from the asset tree.
    assert alarm["owner"] == "user:engineer"
    assert alarm["area_id"] == "U-SIM" and alarm["area_name"] == "Simulated unit"
    assert alarm["area_path"] == ["plant", "U-SIM", "FIC-1001"]
    assert alarm["discipline_label"] == "Process" and alarm["notify"] is True
    assert client.post("/api/rules", json=high(owner="someone")).status_code == 422
    assert client.post("/api/rules", json=high(discipline="magic")).status_code == 422
    # An area set by hand wins over the tree.
    other = make_rule(client, high(name="Other", area="plant"))
    assert client.get(f"/api/alarms/{other['rule_id']}").json()["area_id"] == "plant"
    # "My alarms": the engineer answers for both; the operator for neither.
    client.post("/api/run")
    mine = {row["alarm_id"]: row["mine"] for row in client.get("/api/summary").json()["alarms"]}
    assert mine == {rule["rule_id"]: True, other["rule_id"]: True}
    with client_for(runtime, fake, "operator") as operator:
        rows = operator.get("/api/summary").json()["alarms"]
        assert not any(row["mine"] for row in rows)
        # A rule that notifies the operator's group makes its alarm theirs.
        client.put(
            f"/api/rules/{rule['rule_id']}", json=high(discipline="process", notify=OPERATIONS)
        )
        rows = operator.get("/api/summary").json()
        assert [row["alarm_id"] for row in rows["alarms"] if row["mine"]] == [rule["rule_id"]]
        assert rows["counts"]["mine"] == 1


def test_a_rule_sends_one_notification_to_its_group(client, fake):
    rule = make_rule(client, high(notify={**OPERATIONS, "email": True}))
    assert client.post("/api/run").json()["raised"] == 1
    assert len(fake.notifications) == 1
    sent = fake.notifications[0]
    assert sent["app"] == "alarmcraft" and sent["recipients"] == ["group:operations"]
    assert sent["title"] == "FIC-1001 PV high: raised" and sent["priority"] == "high"
    assert sent["url"] == f"/alarm/alarms/{rule['rule_id']}" and sent["email"] is True
    assert "(pv ≥ 50 m3/h)" in sent["text"] and sent["delivered"] == ["operator"]
    assert "Rule: FIC-1001 PV high" in sent["text"]
    # One conversation per occurrence in Messages.
    occurrence = client.get(f"/api/alarms/{rule['rule_id']}/history").json()["occurrences"][0]
    assert sent["key"] == f"alarm:{rule['rule_id']}:{occurrence['id']}"
    # An alarm in Messages: its icon and filter, and buttons beside Open.
    assert sent["category"] == "alarm"
    assert sent["actions"] == [
        {
            "label": "Acknowledge",
            "href": f"/alarm/api/alarms/{rule['rule_id']}/ack",
            "method": "POST",
        },
        {"label": "Open the rule", "href": f"/alarm/rules/{rule['rule_id']}", "method": "GET"},
    ]
    page = client.get("/api/sent").json()
    row = page["outbox"][0]
    assert row["status"] == "sent" and row["delivered"] == 1
    assert row["rule_id"] == rule["rule_id"] and row["rule_name"] == "FIC-1001 PV high"


def test_acknowledging_settles_the_notification_for_everyone(client, runtime, fake):
    alarm_id = make_rule(client, high(notify=notify(repeat_minutes=30)))["rule_id"]
    client.post("/api/run")
    key = fake.notifications[0]["key"]
    assert fake.resolved_notifications == {}
    # The notification's button POSTs the acknowledgement as the person, with an empty body.
    assert client.post(f"/api/alarms/{alarm_id}/ack", json={}).status_code == 200
    assert fake.resolved_notifications == {("alarmcraft", key): "Acknowledged by engineer"}
    # Settled once: another cycle does not send it again.
    fake.resolved_notifications.clear()
    client.post("/api/run")
    assert fake.resolved_notifications == {}


def test_a_cleared_alarm_settles_its_notification(client, fake):
    alarm_id = make_rule(client, high(notify=notify()))["rule_id"]
    client.post("/api/run")
    key = fake.notifications[0]["key"]
    # The limit rises above the value: the alarm clears, unacknowledged.
    client.put(f"/api/rules/{alarm_id}", json=high(limit=1e9, notify=notify()))
    _later(fake, 1)
    client.post("/api/run")
    assert fake.resolved_notifications == {("alarmcraft", key): "Cleared"}


def test_what_settles_a_notification():
    from alarmcraft.monitor.notifier import Notifier

    now = datetime(2026, 10, 26, 12, tzinfo=UTC)

    def alarm(active: bool, acked: bool, **fields) -> dict:
        state = {"active": active, "occurrence": 7}
        return {"state": state, "acked": acked, "creates": "alarm", **fields}

    settled = Notifier._settled
    assert settled(alarm(True, False), {7}, now) is None
    assert settled(alarm(True, True, acked_by="ana"), {7}, now) == "Acknowledged by ana"
    assert settled(alarm(False, False), {7}, now) == "Cleared"
    assert settled(alarm(True, False), {6}, now) == "Cleared"  # a later occurrence is raised
    assert settled(alarm(True, False, enabled=False), {7}, now) == "Taken out of service"
    assert settled(None, {7}, now) == "Removed from Alarms"
    # A notice wants no acknowledgement but stays open while it is active.
    assert settled(alarm(True, False, creates="notice"), {7}, now) is None
    assert settled(alarm(False, False, creates="notice"), {7}, now) == "Cleared"


def test_a_rule_gathers_its_alarms_into_one_message(client, runtime, fake):
    # Every loop's PV above a low limit: many alarms, one rule, one message after gathering.
    make_rule(client, high(name="Any PV high", assets=[], under=["U-SIM"], limit=-1e9, notify={}))
    raised = client.post("/api/run").json()["raised"]
    assert raised > 2 and fake.notifications == []  # gathers for five minutes by default
    _later(fake, 6)
    client.post("/api/run")
    assert len(fake.notifications) == 1
    sent = fake.notifications[0]
    assert sent["title"] == f"{raised} alarms: Any PV high"
    assert (
        sent["recipients"] == ["user:engineer"] and sent["url"] == "/alarm/alarms?rule=any-pv-high"
    )


def test_the_limit_per_hour_holds_the_rest_in_alarms(client, runtime, fake):
    from alarmcraft.alarms.notices import LIMIT_PER_HOUR

    for number in range(LIMIT_PER_HOUR + 2):
        make_rule(client, high(name=f"PV high {number}", notify=notify()))
    assert client.post("/api/run").json()["raised"] == LIMIT_PER_HOUR + 2
    titles = [item["title"] for item in fake.notifications]
    assert len(titles) == LIMIT_PER_HOUR + 1
    assert titles[-1] == "More alarm notifications are waiting in Alarms"
    page = client.get("/api/sent").json()
    assert [row["status"] for row in page["outbox"]].count("held") == 2
    assert page["limited"] == [{"recipient": "user:engineer", "held": 2}]
    # The alarms are all there, and the limit message goes once an hour.
    assert client.get("/api/summary").json()["counts"]["unacked"] == LIMIT_PER_HOUR + 2
    make_rule(client, high(name="One more", notify=notify()))
    client.post("/api/run")
    assert len(fake.notifications) == LIMIT_PER_HOUR + 1


def test_reminders_until_acknowledged_and_silences(client, fake):
    alarm_id = make_rule(client, high(notify=notify(repeat_minutes=30)))["rule_id"]
    client.post("/api/run")
    assert len(fake.notifications) == 1
    _later(fake, 31)
    client.post("/api/run")
    assert len(fake.notifications) == 2 and fake.notifications[1]["title"].endswith("still active")
    client.post(f"/api/alarms/{alarm_id}/ack")
    _later(fake, 31)
    client.post("/api/run")
    assert len(fake.notifications) == 2  # acknowledged: no more reminders


def test_a_silence_holds_notifications_back_but_not_the_alarm(client, fake):
    silence = client.post(
        "/api/silences", json={"areas": ["U-SIM"], "minutes": 120, "reason": "Shutdown"}
    )
    assert silence.status_code == 201, silence.text
    assert silence.json()["active"] is True
    make_rule(client, high(notify=OPERATIONS))
    assert client.post("/api/run").json()["raised"] == 1
    assert fake.notifications == []
    assert client.get("/api/summary").json()["alarms"][0]["status"] == "unacked"
    assert client.get("/api/silences").json()[0]["active"] is True
    ended = client.post(f"/api/silences/{silence.json()['silence_id']}/end").json()
    assert ended["active"] is False
    actions = [entry["action"] for entry in fake.audit_log if "silence" in entry["action"]]
    assert actions == ["alarmcraft.silence.created", "alarmcraft.silence.ended"]


def test_a_rule_that_does_not_notify_and_a_refused_send(client, fake, runtime):
    make_rule(client, high(notify=notify(enabled=False)))
    client.post("/api/run")
    assert fake.notifications == []
    make_rule(client, high(name="Loud", notify=OPERATIONS))
    original = runtime.notifier.client.notify

    def refuse(*_args, **_kwargs):
        from plantcraft_sdk.client import PlantCraftError

        raise PlantCraftError("PlantCraft is updating", status_code=503)

    runtime.notifier.client.notify = refuse
    client.post("/api/run")
    page = client.get("/api/sent").json()
    assert page["outbox"][0]["status"] == "pending" and "updating" in page["error"]
    runtime.notifier.client.notify = original
    client.post("/api/run")
    assert len(fake.notifications) == 1


def test_notifications_are_checked(client, runtime, fake):
    assert client.post("/api/rules", json=high(notify={"recipients": []})).status_code == 422
    assert (
        client.post("/api/rules", json=high(notify={"recipients": ["everyone"]})).status_code == 422
    )
    no_matcher = {"minutes": 10, "reason": "x"}
    assert client.post("/api/silences", json=no_matcher).status_code == 422
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get("/api/sent").status_code == 200
        assert (
            viewer.post("/api/silences", json={**no_matcher, "areas": ["U-SIM"]}).status_code == 403
        )
    directory = client.get("/api/directory").json()
    assert {group["id"] for group in directory["groups"]} == {"operations", "process-engineering"}
    assert any(person["username"] == "operator" for person in directory["people"])


def _link_status(fake, phase: str, severity: str) -> None:
    """Link's ``status.changed`` condition on FIC-1001 in its loop-health schedule, a minute
    after the last."""

    _later(fake, 1)
    fake.links.events.append(
        {
            "id": len(fake.links.events) + 1,
            "at": fake.now.isoformat(),
            "app": "linkcraft",
            "kind": "linkcraft.status.changed",
            "subject": "asset:FIC-1001",
            "actor": "app:linkcraft",
            "summary": f"FIC-1001 is {severity} in Loop health",
            "refs": ["run:linkcraft:42"],
            "payload": {"schedule_id": "loop-health", "owner": "user:operator"},
            "severity": severity,
            "key": "loop-health:FIC-1001",
            "phase": phase,
            "category": "process",
        }
    )


def link_alarm(**fields) -> dict:
    rule = events_rule(
        ["linkcraft.status.changed"],
        where=fields.pop("where", {"assets": ["FIC-1001"]}),
        **{
            "name": "FIC-1001 loop health bad",
            "priority": "high",
            "action": "Open the loop in Link and follow its finding.",
            "notify": OPERATIONS,
            **fields,
        },
    )
    rule["simple"]["conditions"][0]["event"]["severities"] = ["critical"]
    return rule


def test_a_link_condition_raises_and_its_end_clears_an_alarm(client, fake):
    created = client.post("/api/rules", json=link_alarm())
    assert created.status_code == 201, created.text
    alarm_id = created.json()["rule_id"]
    alarm = client.get(f"/api/alarms/{alarm_id}").json()
    assert alarm["condition"] == "Analytics status changed is open"
    assert alarm["hears"] == ["linkcraft.status.changed"]
    client.post("/api/run")  # the first read starts at the newest event
    # A warning is not bad enough for this rule.
    _link_status(fake, "start", "warning")
    assert client.post("/api/run").json()["raised"] == 0
    _link_status(fake, "start", "critical")
    assert client.post("/api/run").json()["raised"] == 1
    row = client.get(f"/api/alarms/{alarm_id}").json()
    assert (
        row["status"] == "unacked" and row["last_summary"] == "FIC-1001 is critical in Loop health"
    )
    assert row["schedule_id"] == "loop-health" and row["run"] == "run:linkcraft:42"
    # The app named the execution's owner: the alarm answers to them.
    assert row["owner"] == "user:operator"
    assert fake.notifications[-1]["title"] == "FIC-1001 loop health bad: raised"
    _link_status(fake, "end", "ok")
    assert client.post("/api/run").json()["cleared"] == 1
    tried = client.post("/api/rules/try", json={"rule": link_alarm(), "window": "1h"})
    assert tried.status_code == 200 and tried.json()["count"] == 1
    assert client.get(f"/api/alarms/{alarm_id}/history").status_code == 200


def test_a_rule_on_this_assets_events_needs_assets(client):
    assert client.post("/api/rules", json=link_alarm(where={})).status_code == 422
    bad = link_alarm()
    bad["simple"]["conditions"][0]["event"]["kinds"] = ["not a kind!"]
    assert client.post("/api/rules", json=bad).status_code == 422


WORKDAYS = {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:00", "end": "17:00"}


def _at(fake, day: int, clock: str) -> None:
    """Put the plant's clock on 2026-10-<day> at ``clock`` UTC (the 1st is a Thursday)."""

    hours, minutes = (int(part) for part in clock.split(":"))
    fake._now = fake.now.replace(day=day, hour=hours, minute=minutes)


def test_hours_send_to_the_shift_inside_and_hand_over_when_it_opens(client, fake):
    afternoon = {**WORKDAYS, "start": "13:00"}
    # Thursday 12:00: before the shift's hours, nothing is sent.
    shift = notify(recipients=["group:operations"], hours_mode="inside", hours=[afternoon])
    make_rule(client, high(notify=shift))
    client.post("/api/run")
    assert fake.notifications == []
    # At 13:00 the shift takes the alarm, still unacknowledged, over: once.
    _at(fake, 1, "13:05")
    client.post("/api/run")
    assert [item["recipients"] for item in fake.notifications] == [["group:operations"]]
    assert fake.notifications[0]["title"] == "FIC-1001 PV high: still active"
    assert "handed over" in fake.notifications[0]["text"]
    _at(fake, 1, "16:00")
    client.post("/api/run")
    assert len(fake.notifications) == 1


def test_on_call_hears_only_outside_the_hours(client, fake):
    on_call = notify(recipients=["user:admin"], hours_mode="outside", hours=[WORKDAYS])
    make_rule(client, high(notify=on_call))
    client.post("/api/run")  # Thursday 12:00: inside the working hours
    assert fake.notifications == []
    _at(fake, 1, "18:00")
    client.post("/api/run")
    late = fake.notifications[0]
    assert (
        late["recipients"] == ["user:admin"] and late["title"] == "FIC-1001 PV high: still active"
    )


def test_windows_cross_midnight_in_the_policy_time_zone():
    from datetime import datetime, timezone

    from alarmcraft.engine import routing

    policy = {
        "hours_mode": "inside",
        "timezone": "America/Sao_Paulo",
        "hours": [{"days": ["fri"], "start": "17:00", "end": "07:00"}],
    }
    # Friday 2026-10-02 20:00 in São Paulo (UTC-3) is 23:00 UTC.
    assert routing.in_hours(policy, datetime(2026, 10, 2, 23, 0, tzinfo=timezone.utc))
    # Saturday 06:59 local (09:59 UTC) still belongs to Friday night; 07:00 local does not.
    assert routing.in_hours(policy, datetime(2026, 10, 3, 9, 59, tzinfo=timezone.utc))
    assert not routing.in_hours(policy, datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc))
    # Friday 16:00 local is before the window; Thursday night is not in it.
    assert not routing.in_hours(policy, datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc))
    assert not routing.in_hours(policy, datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc))
    whole = {**policy, "hours": [{"days": ["sat", "sun"], "start": "00:00", "end": "24:00"}]}
    assert routing.in_hours(whole, datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc))
    assert routing.in_hours(
        {**whole, "hours_mode": "always"}, datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    )


def test_escalation_reaches_the_coordinator_then_more_people(client, fake):
    engineering = notify(
        recipients=["group:process-engineering"],
        escalations=[
            {"after_minutes": 15, "recipients": ["coordinator"]},
            {"after_minutes": 30, "recipients": ["user:admin", "owner"], "email": True},
        ],
    )
    alarm_id = make_rule(client, high(owner="user:operator", notify=engineering))["rule_id"]
    client.post("/api/run")
    assert [item["recipients"] for item in fake.notifications] == [["group:process-engineering"]]
    _later(fake, 10)
    client.post("/api/run")
    assert len(fake.notifications) == 1
    _later(fake, 6)
    client.post("/api/run")
    step = fake.notifications[1]
    assert step["recipients"] == ["user:engineer"] and step["email"] is False
    assert step["title"] == "FIC-1001 PV high: not acknowledged, escalated"
    assert "Not acknowledged in 15 min (escalation 1)." in step["text"]
    _later(fake, 5)
    client.post("/api/run")
    assert len(fake.notifications) == 2  # each step once
    _later(fake, 10)
    client.post("/api/run")
    step = fake.notifications[2]
    assert sorted(step["recipients"]) == ["user:admin", "user:operator"] and step["email"] is True
    client.post(f"/api/alarms/{alarm_id}/ack")
    _later(fake, 60)
    client.post("/api/run")
    assert len(fake.notifications) == 3
    rows = client.get("/api/sent").json()["outbox"]
    assert sorted(row["step"] or 0 for row in rows) == [0, 1, 2]


def test_acknowledging_stops_escalation_and_a_group_without_coordinator(client, fake):
    steps = [{"after_minutes": 15, "recipients": ["coordinator"]}]
    alarm_id = make_rule(client, high(notify={**OPERATIONS, "escalations": steps}))["rule_id"]
    client.post("/api/run")
    _later(fake, 16)
    client.post("/api/run")
    # Operations has no coordinator: the step is recorded as not sent, and says why.
    assert len(fake.notifications) == 1
    row = client.get("/api/sent").json()["outbox"][0]
    assert row["event"] == "escalation" and row["status"] == "dropped"
    assert "coordinator" in row["error"]
    # A second occurrence acknowledged in time never escalates.
    client.post(f"/api/alarms/{alarm_id}/ack")
    engineering = notify(recipients=["group:process-engineering"], escalations=steps)
    other = make_rule(client, high(name="Second", limit=40, notify=engineering))["rule_id"]
    client.post("/api/run")
    sent = len(fake.notifications)
    client.post(f"/api/alarms/{other}/ack")
    _later(fake, 20)
    client.post("/api/run")
    assert len(fake.notifications) == sent


def test_hours_and_escalations_are_checked(client):
    def status(**fields) -> int:
        body = high(name="X", notify={"recipients": ["owner"], **fields})
        return client.post("/api/rules", json=body).status_code

    assert status(hours_mode="inside") == 422  # no hours
    assert status(hours_mode="inside", hours=[{**WORKDAYS, "start": "7h"}]) == 422
    assert status(hours_mode="inside", hours=[{**WORKDAYS, "end": "07:00"}]) == 422
    assert status(hours_mode="inside", hours=[{**WORKDAYS, "days": []}]) == 422
    assert status(timezone="Mars/Olympus") == 422
    assert status(recipients=["coordinator"]) == 422
    steps = [
        {"after_minutes": 30, "recipients": ["coordinator"]},
        {"after_minutes": 15, "recipients": ["owner"]},
    ]
    assert status(escalations=steps) == 422
    assert status(escalations=[{"after_minutes": 0, "recipients": ["owner"]}]) == 422
    good = status(
        hours_mode="outside",
        hours=[{"days": ["sun", "sat", "sat"], "start": "00:00", "end": "24:00"}],
        timezone="America/Sao_Paulo",
        escalations=list(reversed(steps)),
    )
    assert good == 201
    created = client.get("/api/rules").json()[-1]
    assert created["notify"]["hours"][0]["days"] == ["sat", "sun"]


def test_an_outbox_from_before_escalation_gains_its_step_column(tmp_path):
    import sqlite3

    from plantcraft_sdk.server.store import Database

    from alarmcraft.alarms.notices import NoticeStore

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, alarm_id TEXT NOT NULL,"
            " name TEXT NOT NULL, policy_id TEXT NOT NULL, event TEXT NOT NULL,"
            " priority TEXT NOT NULL, at TEXT NOT NULL, value REAL,"
            " detail TEXT NOT NULL DEFAULT '', recipients_json TEXT NOT NULL,"
            " email INTEGER NOT NULL DEFAULT 0, occurrence INTEGER,"
            " status TEXT NOT NULL DEFAULT 'pending', sent_at TEXT,"
            " delivered INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '')"
        )
    store = NoticeStore(Database(path))
    store.queue(
        {"alarm_id": "a"},
        {"policy_id": "p"},
        "escalation",
        at="2026-10-01T12:00:00+00:00",
        recipients=["user:x"],
        step=1,
    )
    assert store.announced("a", "p", None) == (None, {1})
