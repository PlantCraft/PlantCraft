"""Conditions (SDK 0.26): events with a ``phase`` and a ``key``. A start opens the condition, its
end clears the alarm by itself, and Alarms keeps what is open. A rule about any such event has
one alarm, active while any of its conditions is open."""

from __future__ import annotations

from datetime import timedelta

from tests.conftest import events_rule, make_rule, notify


def _later(fake, minutes: int) -> None:
    fake._now += timedelta(minutes=minutes)


def condition(fake, phase: str, key: str = "service:histcraft-collector", **fields) -> dict:
    """A condition as the suite watch writes it (``processcraft.service.down``)."""

    event = {
        "id": len(fake.links.events) + 1,
        "at": fake.now.isoformat(),
        "app": "processcraft",
        "kind": "processcraft.service.down",
        "subject": "app:processcraft",
        "actor": "user:system",
        "summary": f"Service {key.partition(':')[2]}: exited",
        "refs": [],
        "payload": {"check": key, "detail": "exited (exit code 1)"},
        "severity": "ok" if phase == "end" else "critical",
        "key": key,
        "phase": phase,
        "category": "system",
        **fields,
    }
    fake.links.events.append(event)
    return event


def service_down(for_seconds: float = 300, **fields) -> dict:
    return events_rule(
        ["processcraft.service.down"],
        about="any",
        where={},
        for_seconds=for_seconds,
        **{
            "name": "Service down",
            "priority": "critical",
            "notify": notify(recipients=["group:operations"]),
            **fields,
        },
    )


def test_a_condition_open_five_minutes_raises_and_its_end_clears(client, runtime, fake):
    make_rule(client, service_down())
    client.post("/api/run")  # the first read starts at the newest event
    condition(fake, "start")
    assert client.post("/api/run").json()["raised"] == 0  # open, not five minutes yet
    [opened] = runtime.incoming.open_conditions()
    assert opened["key"] == "service:histcraft-collector" and opened["severity"] == "critical"
    _later(fake, 6)
    condition(fake, "start")  # the same key again: the same alarm, still one
    assert client.post("/api/run").json()["raised"] == 1
    alarm = client.get("/api/alarms/service-down").json()
    assert alarm["status"] == "unacked" and alarm["name"] == "Service down"
    assert alarm["last_summary"] == "Service histcraft-collector: exited"
    assert client.get("/api/rules").json()[0]["alarms"] == 1
    _later(fake, 2)
    condition(fake, "end")
    assert client.post("/api/run").json()["cleared"] == 1
    assert runtime.incoming.open_conditions() == []
    rows = client.get("/api/incoming").json()["events"]
    assert [(row["phase"], row["key"]) for row in rows][:2] == [
        ("end", "service:histcraft-collector"),
        ("start", "service:histcraft-collector"),
    ]


def test_a_condition_that_ends_before_its_wait_raises_nothing(client, fake):
    make_rule(client, service_down())
    client.post("/api/run")
    condition(fake, "start")
    client.post("/api/run")
    _later(fake, 2)
    condition(fake, "end")
    _later(fake, 10)
    assert client.post("/api/run").json()["raised"] == 0
    assert fake.notifications == []


def test_one_alarm_stays_active_while_any_key_is_open(client, fake):
    make_rule(client, service_down(for_seconds=0))
    client.post("/api/run")
    condition(fake, "start")
    condition(fake, "start", key="service:dashcraft")
    assert client.post("/api/run").json()["raised"] == 1
    _later(fake, 1)
    condition(fake, "end")
    assert client.post("/api/run").json()["cleared"] == 0
    _later(fake, 1)
    condition(fake, "end", key="service:dashcraft")
    assert client.post("/api/run").json()["cleared"] == 1


def test_an_event_opens_its_own_page_with_the_same_condition_before(client, runtime, fake):
    """Owner's review, 2026-10-27: an event opens its page (where it came from, its condition's
    earlier starts and ends, the rules that read its kind), not a new rule."""

    make_rule(client, service_down())
    client.post("/api/run")
    condition(fake, "start")
    client.post("/api/run")
    _later(fake, 2)
    condition(fake, "end")
    client.post("/api/run")
    ended, started = client.get("/api/incoming").json()["events"][:2]
    page = client.get(f"/api/incoming/{ended['id']}").json()
    assert page["event"]["kind"] == "processcraft.service.down" and page["open"] is False
    assert [item["id"] for item in page["history"]] == [started["id"]]
    assert [rule["name"] for rule in page["kind_rules"]] == ["Service down"]
    assert client.get("/api/incoming/999999").status_code == 404
    # Open again: the condition's page answers by its key too.
    _later(fake, 1)
    condition(fake, "start")
    client.post("/api/run")
    found = client.get(
        "/api/incoming/condition",
        params={"app": started["app"], "key": "service:histcraft-collector"},
    ).json()
    assert found["open"] is True and found["event"]["phase"] == "start"
