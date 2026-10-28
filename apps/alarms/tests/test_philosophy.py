"""The alarm philosophy (``alarms.philosophy``) and what it holds back: medium and low alarms wait
for the shift summary, critical ones go at once, a flood is one message, a chattering alarm stops
sending, a stale one is no longer reminded, and "no data" waits while the data does not flow.
Also the suite's catalog and the rules it suggests."""

from __future__ import annotations

from datetime import timedelta

from alarmcraft.monitor import suggest
from alarmcraft.monitor.notifier import NO_DATA_KIND as NO_DATA
from tests.conftest import high, make_rule, notify
from tests.test_conditions import condition

OPERATIONS = notify(recipients=["group:operations"])


def _later(fake, minutes: float) -> None:
    fake._now += timedelta(minutes=minutes)


def _titles(fake) -> list[str]:
    return [item["title"] for item in fake.notifications]


def test_medium_waits_for_the_shift_summary_and_critical_goes_at_once(client, fake):
    # The plant's clock starts at 12:00 UTC; the summaries are at 07:00 and 19:00.
    make_rule(client, high(name="Medium PV", priority="medium", notify=OPERATIONS))
    make_rule(client, high(name="Critical PV", priority="critical", notify=notify(
        recipients=["group:operations"], group_seconds=300)))  # fmt: skip
    assert client.post("/api/run").json()["raised"] == 2
    # Critical: at once, past its rule's gathering time.
    assert _titles(fake) == ["Critical PV: raised"]
    rows = {row["name"]: row for row in client.get("/api/sent").json()["outbox"]}
    assert rows["Medium PV"]["status"] == "digest"
    _later(fake, 6 * 60)
    client.post("/api/run")
    assert len(fake.notifications) == 1  # 18:00: not yet
    _later(fake, 61)
    client.post("/api/run")
    summary = fake.notifications[-1]
    assert summary["title"] == "Shift summary: 1 alarms" and summary["category"] == "info"
    assert summary["recipients"] == ["group:operations"]
    assert "[Medium] Medium PV" in summary["text"]
    _later(fake, 10)
    client.post("/api/run")
    assert len(fake.notifications) == 2  # one summary per summary time


def test_a_rule_can_ask_for_always_at_once(client, fake):
    make_rule(client, high(priority="low", notify=notify(always_now=True)))
    client.post("/api/run")
    assert _titles(fake) == ["FIC-1001 PV high: raised"]


def test_a_flood_is_one_message_and_critical_still_goes(client, runtime, fake):
    for number in range(12):
        make_rule(client, high(name=f"PV high {number}", notify=OPERATIONS))
    make_rule(client, high(name="PV critical", priority="critical", notify=OPERATIONS))
    assert client.post("/api/run").json()["raised"] == 13
    titles = _titles(fake)
    assert "PV critical: raised" in titles
    assert "Alarm flood: 13 alarms in 10 min" in titles
    # Not one message per alarm: the first ones before the count, then the flood message.
    assert len(titles) < 13
    held = [row for row in client.get("/api/sent").json()["outbox"] if row["status"] == "held"]
    assert held and all("flood" in row["error"] for row in held)
    [flood] = [item for item in fake.links.events if item["kind"] == "alarmcraft.flood.started"]
    assert flood["payload"]["recipient"] == "group:operations"


def test_a_chattering_alarm_stops_sending_until_the_summary(client, runtime, fake):
    make_rule(client, high(notify=notify()))
    alarm = runtime.alarms.get("fic-1001-pv-high")
    at = fake.now
    for second in (0, 20, 40):
        runtime.alarms.open_occurrence({**alarm, "alarm_id": alarm["alarm_id"]},
                                       (at + timedelta(seconds=second)).isoformat(), 55.0)  # fmt: skip
    rules = runtime.notifier.philosophy()
    assert runtime.notifier.chattering(alarm, at + timedelta(seconds=40), rules)
    assert not runtime.notifier.chattering(alarm, at + timedelta(minutes=5), rules)


def test_a_stale_alarm_is_reviewed_in_the_summary_not_reminded(client, runtime, fake):
    make_rule(client, high(priority="high", notify=notify(repeat_minutes=60)))
    client.post("/api/run")
    assert len(fake.notifications) == 1
    _later(fake, 2 * 60)
    client.post("/api/run")
    assert _titles(fake)[-1] == "FIC-1001 PV high: still active"  # reminded under a day
    _later(fake, 23 * 60)
    client.post("/api/run")
    # Stale: no more reminders, reviewed in the summary instead.
    assert not [title for title in _titles(fake)[2:] if title.endswith("still active")]
    summaries = [item for item in fake.notifications if item["title"].startswith("Shift summary")]
    assert summaries and "Stale alarms" in summaries[-1]["text"]


def test_no_data_sends_nothing_while_the_collector_is_down(client, runtime, fake):
    client.post("/api/run")
    condition(fake, "start")  # the watch: service histcraft-collector down
    client.post("/api/run")
    assert runtime.notifier.data_down()
    alarm = {"alarm_id": "x", "hears": [NO_DATA], "name": "No data", "notify": True}
    runtime.notifier.record(alarm, "raised", fake.now, None, "")
    assert runtime.notifier.inhibited == 1
    condition(fake, "end")
    client.post("/api/run")
    assert not runtime.notifier.data_down()


def test_no_data_of_a_disconnected_source_waits_and_other_sources_do_not(client, runtime, fake):
    client.post("/api/run")
    condition(fake, "start", key="source:north", kind="histcraft.source.disconnected",
              app="histcraft", subject="source:north", summary="Source NORTH disconnected")  # fmt: skip
    client.post("/api/run")
    north = {"alarm_id": "n", "hears": [NO_DATA], "name": "No data",
             "state": {"signal": "north:TI-1"}}  # fmt: skip
    south = {"alarm_id": "s", "hears": [NO_DATA], "name": "No data",
             "state": {"signal": "south:TI-1"}}  # fmt: skip
    assert runtime.notifier.data_down(north) == "Source NORTH disconnected"
    assert runtime.notifier.data_down(south) == "" and runtime.notifier.data_down() == ""
    runtime.notifier.record(north, "raised", fake.now, None, "")
    assert runtime.notifier.inhibited == 1
    condition(fake, "start", key="collector", kind="histcraft.collector.stalled", app="histcraft")
    client.post("/api/run")
    assert runtime.notifier.data_down(south)  # the collector stalled: every source waits


def test_the_philosophy_is_read_changed_and_measured(client, fake):
    found = client.get("/api/philosophy").json()
    assert found["per_person_hour"] == 6 and found["digest"] == ["medium", "low"]
    assert found["next_summary"].startswith("2026-10-01T19:00")
    body = {**found["defaults"], "digest_times": ["06:00"], "flood_alarms": 20,
            "statement": "An alarm needs an action."}  # fmt: skip
    changed = client.put("/api/philosophy", json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()["updated_by"] == "engineer" and changed.json()["flood_alarms"] == 20
    assert changed.json()["next_summary"].startswith("2026-10-02T06:00")
    for bad in (
        {"digest": ["critical"], "immediate": []},
        {"target_low": 10},
        {"digest_times": ["25:00"]},
        {"immediate": ["medium"]},
    ):
        assert client.put("/api/philosophy", json={**body, **bad}).status_code == 422
    figures = {item["id"]: item for item in client.get("/api/performance").json()["figures"]}
    assert figures["peak"]["target"] == "≤ 20"


def test_the_catalog_lists_what_apps_declare_and_starts_rules(client, runtime, fake):
    fake.declare_events(
        {
            "app": {"id": "linkcraft"},
            "publishes": {
                "events": [
                    {"name": "run.failed", "title": "Run failed", "severity": "warning",
                     "category": "run", "rule": {"when": "event", "priority": "high"}},
                    {"name": "schedule.stalled", "title": "Schedule stalled", "phase": "interval",
                     "rule": {"when": "open", "minutes": 30, "enabled": True}},
                ]
            },
        }
    )  # fmt: skip
    page = client.get("/api/catalog").json()
    [app] = page["apps"]
    assert [event["kind"] for event in app["events"]] == [
        "linkcraft.run.failed",
        "linkcraft.schedule.stalled",
    ]
    prefill = client.get("/api/rules/from-catalog", params={"kind": "linkcraft.run.failed"}).json()
    [first] = prefill["simple"]["conditions"]
    assert first["event"]["kinds"] == ["linkcraft.run.failed"] and prefill["priority"] == "high"
    assert prefill["where"] == {"anywhere": True}
    made = make_rule(client, prefill)
    stalled = client.get(
        "/api/rules/from-catalog", params={"kind": "linkcraft.schedule.stalled"}
    ).json()
    [open_one] = stalled["simple"]["conditions"]
    assert open_one["test"] == "open" and open_one["for_seconds"] == 1800
    assert client.get("/api/rules/from-catalog", params={"kind": "x.y.z"}).status_code == 404
    page = client.get("/api/catalog").json()
    assert page["apps"][0]["events"][0]["rules"] == [
        {"rule_id": made["rule_id"], "name": "Run failed"}
    ]
    # A suggestion marked enabled (a system event) is created once, by itself.
    catalog = suggest.catalog_of(runtime.service_client)
    first = suggest.apply_enabled(runtime.rules, catalog, taken=set())
    assert [rule["name"] for rule in first] == ["Schedule stalled"]
    assert suggest.apply_enabled(runtime.rules, catalog, taken=set()) == []
