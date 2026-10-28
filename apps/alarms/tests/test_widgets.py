"""Alarms' widgets for the PlantCraft Overview (contract v1)."""

from __future__ import annotations

from datetime import timedelta

from plantcraft_sdk import apptest

from tests.conftest import high


def test_the_widgets_count_and_list_the_alarms_that_need_action(client):
    listed = client.get("/api/widgets").json()
    assert listed["version"] == 1
    assert [item["id"] for item in listed["widgets"] if item["default"]] == ["active"]
    assert apptest.widget_problems(client, "") == []
    calm = client.get("/api/widgets/active").json()
    assert calm["kind"] == "number" and calm["value"] == 0 and calm["state"] == "ok"
    assert calm["href"].endswith("/alarms")

    alarm_id = client.post("/api/rules", json=high()).json()["rule_id"]
    client.post("/api/run")
    active = client.get("/api/widgets/active").json()
    assert active["value"] == 1 and active["state"] == "alarm" and "1" in active["label"]
    rows = client.get("/api/widgets/summary").json()
    assert rows["kind"] == "list" and rows["items"][0]["href"].endswith(f"/alarms/{alarm_id}")
    assert rows["items"][0]["state"] == "alarm" and rows["href"].endswith("/alarms")
    raised = client.get("/api/widgets/raised").json()
    assert raised["kind"] == "number" and raised["value"] == 1 and raised["state"] == "ok"
    assert raised["href"].endswith("/performance")

    assert apptest.widget_problems(client, "") == []
    priorities = client.get("/api/widgets/priorities").json()
    assert sum(part["value"] for part in priorities["parts"]) == 1
    rate = client.get("/api/widgets/rate").json()
    assert rate["kind"] == "columns" and rate["value"] == 1 and rate["step"] == "hour"
    assert len(rate["buckets"]) in (24, 25)
    assert sum(sum(values) for _, values in rate["buckets"]) == 1
    actors = client.get("/api/widgets/bad-actors").json()
    assert actors["kind"] == "bars" and actors["bars"][0]["value"] == 1

    client.post(f"/api/alarms/{alarm_id}/ack")
    assert client.get("/api/widgets/active").json()["state"] == "warning"
    assert client.get("/api/widgets/nope").status_code == 404


def test_a_rule_off_dashboards_stays_in_alarms_only(client, fake):
    rule = client.post("/api/rules", json=high(dashboards=False))
    assert rule.status_code == 201, rule.text
    assert rule.json()["dashboards"] is False
    client.post("/api/run")
    # Listed in Alarms, but no asset colour and no widget count.
    assert client.get("/api/summary").json()["counts"]["active"] == 1
    assert ("alarmcraft", "asset:FIC-1001", "alarm_state") not in fake.links.results
    assert client.get("/api/widgets/active").json()["value"] == 0


def test_the_load_widgets_judge_the_last_day_against_the_philosophy(client, runtime, fake):
    # A quiet plant: every shape says so in words, the rate still shows its target.
    rate = client.get("/api/widgets/rate").json()
    assert rate["kind"] == "columns" and rate["value"] == 0 and not rate.get("buckets")
    assert rate["empty"] == "No alarm raised in the last 24 hours."
    assert rate["target"] == 6 and rate["target_label"] == "Target 6 an hour"
    # Bottom first: the highest priority, in the colours of the split by priority.
    assert [(s["label"], s["state"]) for s in rate["stacks"]] == [
        ("Critical", "critical"),
        ("High", "high"),
        ("Medium", "medium"),
        ("Low", "unknown"),
    ]
    actors = client.get("/api/widgets/bad-actors").json()
    assert actors["kind"] == "bars" and actors["bars"] == []
    assert actors["empty"] == "No alarm raised in the last 7 days."
    figures = client.get("/api/widgets/performance").json()
    assert figures["kind"] == "facts" and figures["state"] == "ok"
    assert figures["status"] == "Within the ISA-18.2 targets"
    assert [fact["label"] for fact in figures["facts"]][:4] == [
        "Average alarms per hour",
        "Time in flood",
        "Chattering alarms",
        "Stale alarms",
    ]
    assert {fact["state"] for fact in figures["facts"]} == {"ok"}

    # The target is the installation's own (Philosophy), not a constant.
    found = client.get("/api/philosophy").json()
    changed = client.put("/api/philosophy", json={**found["defaults"], "per_person_hour": 4})
    assert changed.status_code == 200, changed.text
    rate = client.get("/api/widgets/rate").json()
    assert rate["target"] == 4 and rate["target_label"] == "Target 4 an hour"

    alarm_id = client.post("/api/rules", json=high()).json()["rule_id"]
    client.post("/api/run")
    rate = client.get("/api/widgets/rate").json()
    assert rate["value"] == 1 and rate["state"] == "ok"
    # One high alarm: its hour's column holds one in the High stack.
    assert [values for _, values in rate["buckets"] if any(values)] == [[0, 1, 0, 0]]
    assert all(b[0] < a[0] for b, a in zip(rate["buckets"], rate["buckets"][1:], strict=False))
    bar = client.get("/api/widgets/bad-actors").json()["bars"][0]
    assert bar["label"] == "FIC-1001 PV high" and bar["value"] == 1
    assert bar["detail"] == "100 % of the load" and bar["state"] == "high"
    assert bar["href"].endswith(f"/alarms/{alarm_id}")

    # It chatters an hour ago: the indicators out of target come first, in their colour.
    alarm = runtime.alarms.get(alarm_id)
    for second in range(0, 36, 3):
        at = fake.now - timedelta(hours=1) + timedelta(seconds=second)
        runtime.alarms.open_occurrence(alarm, at.isoformat(), 60.0)
    figures = client.get("/api/widgets/performance").json()
    assert figures["state"] == "alarm" and figures["status"].startswith("Out of target: ")
    chattering = figures["facts"][0]
    assert {key: chattering[key] for key in ("label", "value", "state")} == {
        "label": "Chattering alarms",
        "value": "1",
        "state": "alarm",
    }
    # Hovered, each figure says what it means and its target.
    assert chattering["detail"].startswith("Alarms that raise and clear again and again")
    assert "Target: none" in chattering["detail"]
    assert [fact["state"] for fact in figures["facts"]][-1] == "ok"
    rate = client.get("/api/widgets/rate").json()
    assert rate["value"] == 13 and sum(sum(values) for _, values in rate["buckets"]) == 13
    assert rate["state"] == "ok"  # 13 in a day is still within 4 an hour on average
    assert apptest.widget_problems(client, "") == []
