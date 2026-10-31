"""PlantCraft Alarms' HTTP API against the fake PlantCraft with the Simulator's loops."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.conftest import PV, client_for, high, make_rule
from tests.plant import NOW


def test_health_and_me(client):
    assert client.get("/healthz").json()["status"] == "ok"
    me = client.get("/api/me").json()
    assert me["username"] == "engineer" and me["can_edit"] is True
    # No email server in PlantCraft: a rule does not offer email.
    assert me["email_ready"] is False


def test_me_says_when_platform_email_is_ready(runtime, fake):
    fake.email_ready = True
    with client_for(runtime, fake) as client:
        assert client.get("/api/me").json()["email_ready"] is True


@pytest.mark.parametrize(
    ("user", "role"), [("admin", "admin"), ("engineer", "editor"), ("operator", "viewer")]
)
def test_me_role_shows_an_admin_as_admin(runtime, fake, user, role):
    with client_for(runtime, fake, user) as client:
        assert client.get("/api/me").json()["role"] == role


def test_create_read_change_delete(client, fake):
    created = client.post("/api/rules", json=high())
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["rule_id"] == "fic-1001-pv-high" and rule["alarms"] == 1
    assert rule["editor"] == "simple" and rule["sentence"] == "pv ≥ 50 m3/h"
    alarm = client.get("/api/alarms/fic-1001-pv-high").json()
    assert alarm["status"] == "normal" and alarm["condition"] == "pv ≥ 50 m3/h"
    assert alarm["asset_id"] == "FIC-1001" and alarm["rule_id"] == "fic-1001-pv-high"
    assert alarm["owner"] == "user:engineer"  # the creator, unless someone else is named

    changed = client.put(
        f"/api/rules/{rule['rule_id']}",
        json=high(priority="critical", base_updated_at=rule["updated_at"]),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["priority"] == "critical"
    assert client.get("/api/alarms/fic-1001-pv-high").json()["priority"] == "critical"
    stale = client.put(
        f"/api/rules/{rule['rule_id']}", json=high(base_updated_at=rule["updated_at"])
    )
    assert stale.status_code == 409

    assert client.delete(f"/api/rules/{rule['rule_id']}").status_code == 204
    assert client.get(f"/api/rules/{rule['rule_id']}").status_code == 404
    assert client.get("/api/alarms/fic-1001-pv-high").status_code == 404
    actions = [
        entry["action"] for entry in fake.audit_log if entry["action"].startswith("alarmcraft.")
    ]
    assert actions == [
        "alarmcraft.rule.created",
        "alarmcraft.rule.changed",
        "alarmcraft.rule.deleted",
    ]


def test_invalid_rules_are_refused(client):
    assert client.post("/api/rules", json=high(limit=None)).status_code == 422
    assert client.post("/api/rules", json=high(priority="urgent")).status_code == 422
    assert client.post("/api/rules", json=high(assets=[])).status_code == 422
    assert client.post("/api/rules", json=high(signal_id=PV)).status_code == 422  # both
    assert client.post("/api/rules", json=high(role="PV!")).status_code == 422
    assert client.post("/api/rules", json=high(creates="page")).status_code == 422
    assert client.post("/api/rules", json=high(kind="events")).status_code == 422


def test_one_rule_covers_every_loop_of_a_branch(runtime, fake, client):
    rule = make_rule(client, high(name="PV high", assets=[], under=["U-SIM"], limit=1e9))
    loops = [item["id"] for item in fake.assets if item.get("kind") == "loop"]
    assert rule["alarms"] == len(loops) > 2
    alarms = {row["alarm_id"]: row for row in rule["alarm_rows"]}
    assert "pv-high--fic-1001" in alarms
    assert alarms["pv-high--fic-1001"]["name"] == "PV high · FIC-1001"
    counts = client.post("/api/run").json()
    assert counts["evaluated"] == len(loops) and counts["raised"] == 0
    # Narrowed to one asset: the other alarms leave, the one kept keeps its id.
    narrowed = client.put(
        f"/api/rules/{rule['rule_id']}", json=high(name="PV high", assets=["FIC-1001"], limit=1e9)
    ).json()
    assert [row["alarm_id"] for row in narrowed["alarm_rows"]] == ["pv-high"]
    assert client.get("/api/rules").json()[0]["alarms"] == 1


def test_a_rule_turned_off_puts_its_alarms_out_of_service(client):
    rule = make_rule(client, high())
    client.post("/api/run")
    off = client.post(f"/api/rules/{rule['rule_id']}/enabled", json={"enabled": False}).json()
    assert off["enabled"] is False
    assert off["alarm_rows"][0]["status"] == "out_of_service"
    assert client.post("/api/run").json()["evaluated"] == 0
    back = client.post(f"/api/rules/{rule['rule_id']}/enabled", json={"enabled": True}).json()
    assert back["alarm_rows"][0]["status"] == "normal"


def test_viewers_read_but_never_act(runtime, fake, client):
    alarm = make_rule(client, high())
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get("/api/alarms").status_code == 200
        assert viewer.get("/api/rules").status_code == 200
        assert viewer.get("/api/summary").status_code == 200
        assert viewer.get("/api/incoming").status_code == 200
        assert viewer.post("/api/rules", json=high()).status_code == 403
        assert viewer.post(f"/api/alarms/{alarm['rule_id']}/ack").status_code == 403
    with client_for(runtime, fake, "outsider") as outsider:
        assert outsider.get("/api/alarms").status_code == 403
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get("/api/alarms").status_code == 401


def test_a_cycle_raises_records_and_publishes(runtime, fake, client):
    alarm_id = make_rule(client, high())["rule_id"]
    counts = client.post("/api/run").json()
    assert counts["raised"] == 1 and counts["evaluated"] == 1

    summary = client.get("/api/summary").json()
    assert summary["counts"]["unacked"] == 1 and summary["counts"]["active"] == 1
    row = summary["alarms"][0]
    assert row["alarm_id"] == alarm_id and row["status"] == "unacked"
    assert row["signal"] == PV and row["value"] > 50 and row["raised_at"]

    occurrences = runtime.alarms.occurrences()
    assert len(occurrences) == 1 and occurrences[0]["ended_at"] is None
    assert {item["action"] for item in client.get("/api/journal").json()} == {"raised", "created"}

    events = [item for item in fake.links.events if item["kind"] == "alarmcraft.alarm.raised"]
    assert len(events) == 1 and events[0]["subject"] == "asset:FIC-1001"
    assert "High alarm" in events[0]["summary"]
    result = fake.links.results[("alarmcraft", "asset:FIC-1001", "alarm_state")]
    assert result["status"] == "alarm"
    assert fake.links.runs and fake.links.schedules["alarmcraft"]

    # Acknowledged: still active; a second cycle raises nothing new.
    acked = client.post(f"/api/alarms/{alarm_id}/ack").json()
    assert acked["status"] == "acked" and acked["acked_by"] == "engineer"
    fake._now = NOW + timedelta(minutes=1)
    assert client.post("/api/run").json()["raised"] == 0
    assert runtime.alarms.occurrences()[0]["acked_by"] == "engineer"


def test_a_changed_limit_clears_and_starts_again(runtime, fake, client):
    rule = make_rule(client, high())
    client.post("/api/run")
    client.put(
        f"/api/rules/{rule['rule_id']}", json=high(limit=500.0, base_updated_at=rule["updated_at"])
    )
    occurrence = runtime.alarms.occurrences()[0]
    assert occurrence["ended_at"] is not None
    fake._now = NOW + timedelta(minutes=1)
    client.post("/api/run")
    assert client.get(f"/api/alarms/{rule['rule_id']}").json()["status"] == "normal"


def test_a_change_of_words_keeps_the_alarm_raised(runtime, client):
    rule = make_rule(client, high())
    client.post("/api/run")
    client.put(f"/api/rules/{rule['rule_id']}", json=high(action="Call the field operator"))
    alarm = client.get(f"/api/alarms/{rule['rule_id']}").json()
    assert alarm["status"] == "unacked" and alarm["action"] == "Call the field operator"
    assert runtime.alarms.occurrences()[0]["ended_at"] is None


def test_acknowledge_all_and_return_to_normal(runtime, fake, client):
    first = make_rule(client, high())["rule_id"]
    second = make_rule(client, high(name="FIC-1001 PV high 2", priority="low"))["rule_id"]
    client.post("/api/run")
    assert client.post("/api/ack", json={"alarm_ids": [second]}).json() == {"acknowledged": 1}
    assert client.post("/api/ack", json={}).json() == {"acknowledged": 1}
    assert {row["status"] for row in client.get("/api/summary").json()["alarms"]} == {"acked"}
    assert first != second


def test_shelve_and_out_of_service(runtime, fake, client):
    alarm_id = make_rule(client, high())["rule_id"]
    bad = client.post(f"/api/alarms/{alarm_id}/shelve", json={"minutes": 30, "reason": ""})
    assert bad.status_code == 422
    # Shelving is time-limited by priority (the philosophy: 1 h critical ... 24 h low).
    priority = client.get(f"/api/alarms/{alarm_id}").json()["priority"]
    longest = {"critical": 60, "high": 240, "medium": 720, "low": 1440}[priority]
    too_long = {"minutes": longest + 1, "reason": "Instrument under repair"}
    refused = client.post(f"/api/alarms/{alarm_id}/shelve", json=too_long)
    assert refused.status_code == 422 and "at most" in refused.text
    shelved = client.post(
        f"/api/alarms/{alarm_id}/shelve", json={"minutes": 30, "reason": "Instrument under repair"}
    ).json()
    assert shelved["status"] == "shelved" and shelved["shelve_reason"] == "Instrument under repair"
    assert client.post("/api/run").json()["raised"] == 0  # evaluated, but raises nothing
    assert runtime.alarms.occurrences() == []
    unshelved = client.post(f"/api/alarms/{alarm_id}/unshelve").json()
    assert unshelved["status"] == "unacked"  # still active: annunciated again

    off = client.post(f"/api/alarms/{alarm_id}/enabled", json={"enabled": False}).json()
    assert off["status"] == "out_of_service"
    assert client.get("/api/summary").json()["out_of_service"][0]["alarm_id"] == alarm_id
    assert (
        client.post(f"/api/alarms/{alarm_id}/enabled", json={"enabled": True}).json()["status"]
        == "normal"
    )
    actions = [item["action"] for item in client.get(f"/api/journal?alarm={alarm_id}").json()]
    assert {"shelved", "unshelved", "out_of_service", "in_service"} <= set(actions)


def test_try_a_rule_on_history(client):
    tried = client.post("/api/rules/try", json={"rule": high(), "window": "6h"})
    assert tried.status_code == 200, tried.text
    body = tried.json()
    assert body["signal"] == PV and body["count"] >= 1 and len(body["chart"]["t"]) > 100
    assert body["subjects"] == 1 and body["messages"] >= 1
    quiet = client.post("/api/rules/try", json={"rule": high(limit=500), "window": "6h"}).json()
    assert quiet["count"] == 0 and quiet["messages"] == 0
    unknown = client.post("/api/rules/try", json={"rule": high(role="nope")}).json()
    assert unknown["count"] == 0 and "nope" in " ".join(unknown["problems"])
    assert client.post("/api/rules/try", json={"rule": high(), "window": "-1h"}).status_code == 422
    branch = high(assets=[], under=["U-SIM"])
    many = client.post("/api/rules/try", json={"rule": branch, "window": "6h"}).json()
    assert many["subjects"] > 2 and len(many["alarms"]) == many["tried"]


def test_alarm_history_page(client):
    alarm_id = make_rule(client, high())["rule_id"]
    client.post("/api/run")
    page = client.get(f"/api/alarms/{alarm_id}/history?window=1h").json()
    assert page["alarm"]["alarm_id"] == alarm_id and len(page["occurrences"]) == 1
    assert len(page["chart"]["t"]) > 10 and page["problem"] == ""


def test_performance_endpoint(client):
    make_rule(client, high())
    client.post("/api/run")
    report = client.get("/api/performance?window=24h").json()
    assert report["total"] == 1 and report["top"][0]["name"] == "FIC-1001 PV high"
    assert {item["id"] for item in report["figures"]} >= {"per_hour", "flood", "chattering"}


def test_asset_page_lists_its_alarms(client):
    make_rule(client, high())
    page = client.get("/api/asset-alarms?asset=FIC-1001").json()
    assert page["asset"]["name"] == "FIC-1001" and len(page["alarms"]) == 1
    assert client.get("/api/asset-alarms?asset=nowhere").status_code == 404


def test_pickers(client):
    assets = client.get("/api/assets?q=FIC").json()
    assert any(item["id"] == "FIC-1001" and "pv" in item["signals"] for item in assets)
    signals = client.get("/api/signals?q=FIC-1001").json()
    assert PV in {item["id"] for item in signals}


def test_without_an_app_key_nothing_runs(tmp_path, fake):
    from tests.conftest import make_runtime

    rt = make_runtime(tmp_path, fake, app_key=False)
    try:
        with client_for(rt, fake) as client:
            make_rule(client, high())
            assert client.post("/api/run").status_code == 503
            assert client.get("/api/status").json()["service_key"] is False
    finally:
        rt.shutdown()


def test_history_replay_fills_the_past(runtime, fake, client):
    alarm_id = make_rule(client, high())["rule_id"]
    written = runtime.replay.run(6, "operator")
    assert written[alarm_id]["occurrences"] >= 1
    occurrences = runtime.alarms.occurrences()
    assert occurrences and all(
        item["ended_at"] and item["acked_by"] == "operator" for item in occurrences
    )
    for item in occurrences:
        assert item["started_at"] < item["acked_at"]
    actions = {item["action"] for item in client.get("/api/journal?window=7d").json()}
    assert {"raised", "cleared", "acknowledged"} <= actions
    assert client.get("/api/performance?window=24h").json()["mean_ack_seconds"] is not None
    # Again: the past is already there.
    assert runtime.replay.run(6, "operator")[alarm_id].get("skipped") is True
    assert len(runtime.alarms.occurrences()) == len(occurrences)


def test_history_replay_endpoint(runtime, fake, client):
    make_rule(client, high())
    started = client.post("/api/history/replay", json={"hours": 6, "acknowledged_by": "operator"})
    assert started.status_code == 202 and started.json()["started"] is True
    assert client.post("/api/history/replay", json={"hours": 0}).status_code == 422
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.post("/api/history/replay", json={}).status_code == 403
