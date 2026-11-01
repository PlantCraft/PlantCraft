"""Rules on events and executions: what the apps report (``/api/v1/events``) read each cycle,
counted per asset within a window, raised as alarms or notices to the responsible the app
names, cleared, and inhibited while their schedule has failed; one alarm per execution; Incoming;
the editors' endpoints (blocks, check, the Simple form, Python only for administrators); and the
rules of an older Alarms rewritten as Simple rules."""

from __future__ import annotations

import json
from datetime import timedelta

from alarmcraft.alarms.rules import RuleStore, from_legacy
from tests.conftest import PV, client_for, events_rule, high, make_rule, make_runtime, notify


def _later(fake, minutes: int) -> None:
    fake._now += timedelta(minutes=minutes)


def report(
    fake,
    kind: str,
    asset: str = "FIC-1001",
    *,
    severity: str | None = "critical",
    schedule: str = "loop-health-15m",
    owner: str = "user:operator",
    output: str = "health",
    subject: str | None = None,
) -> dict:
    """An event as Link publishes it (``POST /api/v1/events``), kept by the fake PlantCraft."""

    payload = {"schedule_id": schedule, "algorithm_id": "loop-health", "version": 3}
    payload.update(owner=owner, output=output)
    if severity:
        payload["severity"] = severity
    event = {
        "id": len(fake.links.events) + 1,
        "at": fake.now.isoformat(),
        "app": "linkcraft",
        "kind": kind,
        "subject": subject or f"asset:{asset}",
        "actor": "app:linkcraft",
        "summary": f"{asset} health {severity}",
        "refs": [f"asset:{asset}", "run:linkcraft/run-1"],
        "payload": payload,
    }
    fake.links.events.append(event)
    return event


def critical_three_times(**fields) -> dict:
    """Any asset Link names, critical three times in an hour (one alarm per asset)."""

    rule = events_rule(
        ["linkcraft.output.status"],
        test="count",
        count=fields.pop("count", 3),
        window_minutes=fields.pop("window_minutes", 60),
        **{
            "name": "Loop critical 3 times in 1 h",
            "priority": "medium",
            # Medium: it would wait for the shift summary (tests/test_philosophy.py).
            "notify": notify(always_now=True),
            "action": "Open the loop in Link and follow its finding.",
            **fields,
        },
    )
    rule["simple"]["conditions"][0]["event"]["severities"] = ["critical"]
    return rule


def schedule_failed(**fields) -> dict:
    return events_rule(
        ["linkcraft.run.failed", "linkcraft.schedule.stalled"],
        test="count",
        count=1,
        window_minutes=60,
        **{
            "name": "Link schedule failed",
            "creates": "notice",
            "priority": "high",
            # A notice waits for the shift summary unless its rule says otherwise.
            "notify": notify(always_now=True),
            **fields,
        },
    )


def test_three_criticals_in_an_hour_raise_one_alarm_for_the_schedule_owner(client, fake):
    rule = make_rule(client, critical_three_times())
    assert rule["alarms"] == 0 and rule["where_words"]
    assert rule["sentence"] == "Analytics output status happened 3 times in 1 h"
    client.post("/api/run")  # the first read starts at the newest event
    report(fake, "linkcraft.output.status")
    _later(fake, 1)
    report(fake, "linkcraft.output.status", severity="warning")  # not counted
    report(fake, "linkcraft.output.status", "TIC-1104")  # another loop: its own count
    _later(fake, 15)
    report(fake, "linkcraft.output.status")
    assert client.post("/api/run").json()["raised"] == 0
    alarm_id = "loop-critical-3-times-in-1-h--fic-1001"
    alarm = client.get(f"/api/alarms/{alarm_id}").json()
    assert alarm["status"] == "normal" and alarm["owner"] == "user:operator"
    assert alarm["name"] == "Loop critical 3 times in 1 h · FIC-1001"
    _later(fake, 15)
    report(fake, "linkcraft.output.status")
    assert client.post("/api/run").json()["raised"] == 1
    alarm = client.get(f"/api/alarms/{alarm_id}").json()
    assert alarm["status"] == "unacked" and alarm["schedule_id"] == "loop-health-15m"
    assert alarm["run"] == "run:linkcraft/run-1"
    # The responsible Link named in its events hears about it, nobody else.
    assert [item["recipients"] for item in fake.notifications] == [["user:operator"]]
    assert fake.notifications[0]["title"] == "Loop critical 3 times in 1 h · FIC-1001: raised"
    page = client.get(f"/api/alarms/{alarm_id}/history").json()
    # The warning was heard, not counted.
    assert [item["counted"] for item in page["events"]].count(True) == 3
    # The hour passes with no new critical: the alarm clears.
    _later(fake, 61)
    assert client.post("/api/run").json()["cleared"] == 1
    assert client.get(f"/api/alarms/{alarm_id}").json()["status"] == "rtn_unacked"
    # TIC-1104 counted once, never raised.
    assert client.get(f"/api/rules/{rule['rule_id']}").json()["alarms"] == 2


def test_a_failed_schedule_is_a_notice_and_inhibits_its_loops(client, runtime, fake):
    failed = make_rule(client, schedule_failed())
    make_rule(client, critical_three_times(count=1))
    client.post("/api/run")
    report(fake, "linkcraft.run.failed", severity=None)
    assert client.post("/api/run").json()["raised"] == 1
    notice = client.get(f"/api/rules/{failed['rule_id']}").json()["alarm_rows"][0]
    # A notice needs no acknowledgement, and stays out of the alarm performance.
    assert notice["creates"] == "notice" and notice["status"] == "acked"
    assert client.get("/api/performance").json()["total"] == 0
    assert [item["title"] for item in fake.notifications] == [
        "Link schedule failed · FIC-1001: raised"
    ]
    # A notice is information in Messages: no Acknowledge button, only the way to its rule.
    sent = fake.notifications[0]
    assert sent["category"] == "info"
    assert sent["actions"] == [
        {"label": "Open the rule", "href": f"/alarm/rules/{failed['rule_id']}", "method": "GET"}
    ]
    # While the schedule's failure is active, its loops' alarms send nothing (their cause).
    _later(fake, 1)
    report(fake, "linkcraft.output.status")
    assert client.post("/api/run").json()["raised"] == 1
    assert len(fake.notifications) == 1
    assert client.get("/api/sent").json()["inhibited"] == 1
    summary = client.get("/api/summary").json()
    assert summary["counts"]["notices_24h"] == 1 and summary["counts"]["last_24h"] == 1


def test_one_alarm_per_execution_and_its_assets(tmp_path, fake):
    fake.links.schedules["linkcraft"] = [
        {"app": "linkcraft", "id": "loop-health-15m", "name": "Loop health", "cadence": "15m",
         "next_run": None, "enabled": True, "url": None, "updated_at": fake.now.isoformat(),
         "subjects": ["asset:FIC-1001", "asset:TIC-1104"]},
        {"app": "linkcraft", "id": "rounds", "name": "Rounds", "cadence": "1h", "next_run": None,
         "enabled": True, "url": None, "updated_at": fake.now.isoformat(), "subjects": []},
    ]  # fmt: skip
    runtime = make_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake) as client:
            _per_execution(client, fake)
    finally:
        runtime.shutdown()


def _per_execution(client, fake) -> None:
    executions = client.get("/api/executions").json()
    assert {item["id"]: item["assets"] for item in executions} == {
        "linkcraft:loop-health-15m": 2,
        "linkcraft:rounds": 0,
    }
    where = {"executions": ["linkcraft:loop-health-15m", "linkcraft:rounds"], "per": "execution"}
    rule = make_rule(client, schedule_failed(where=where))
    ids = sorted(row["alarm_id"] for row in rule["alarm_rows"])
    assert ids == [
        "link-schedule-failed--execution-linkcraft-loop-health-15m",
        "link-schedule-failed--execution-linkcraft-rounds",
    ]
    client.post("/api/run")
    report(fake, "linkcraft.run.failed", severity=None, schedule="rounds", subject="app:linkcraft")
    assert client.post("/api/run").json()["raised"] == 1
    raised = client.get("/api/alarms/link-schedule-failed--execution-linkcraft-rounds").json()
    assert raised["active"] and raised["schedule_id"] == "rounds"  # a notice: no ack needed
    # Over the execution's assets: one alarm per asset it runs on.
    each = make_rule(
        client,
        high(name="Loop PV high", limit=1e9)
        | {"where": {"executions": ["linkcraft:loop-health-15m"]}},
    )
    assert sorted(row["asset_id"] for row in each["alarm_rows"]) == ["FIC-1001", "TIC-1104"]


def test_incoming_lists_what_came_and_the_rules_it_counted_for(client, runtime, fake):
    report(fake, "linkcraft.output.status")  # before Alarms first read: shown, not judged
    make_rule(client, critical_three_times())
    client.post("/api/run")
    _later(fake, 1)
    report(fake, "linkcraft.output.status")
    report(fake, "linkcraft.finding.opened", severity="warning")
    client.post("/api/run")
    page = client.get("/api/incoming").json()
    assert [item["kind"] for item in page["events"]] == [
        "linkcraft.finding.opened",
        "linkcraft.output.status",
        "linkcraft.output.status",
    ]
    assert page["events"][1]["rule_names"] == ["Loop critical 3 times in 1 h"]
    assert page["events"][0]["rules"] == [] and page["events"][2]["rules"] == []
    only = client.get("/api/incoming", params={"severity": "warning"}).json()["events"]
    assert [item["kind"] for item in only] == ["linkcraft.finding.opened"]
    # A new rule starts from an event that came in.
    started = client.get(f"/api/rules/from-event/{page['events'][0]['id']}").json()
    [condition] = started["simple"]["conditions"]
    assert condition["event"]["kinds"] == ["linkcraft.finding.opened"]
    assert condition["event"]["severities"] == ["warning"]
    assert started["where"]["assets"] == ["FIC-1001"]
    assert client.post("/api/rules", json=started).status_code == 201
    assert client.get("/api/rules/from-event/999").status_code == 404
    # Test on the events that came in.
    tried = client.post("/api/rules/try", json={"rule": critical_three_times(count=1)}).json()
    assert tried["count"] >= 1 and tried["alarms"][0]["label"] == "FIC-1001"


def test_event_rules_are_checked(client):
    def status(**event) -> int:
        rule = critical_three_times()
        rule["simple"]["conditions"][0]["event"].update(event)
        return client.post("/api/rules", json=rule).status_code

    assert status(kinds=["output"]) == 422
    assert status(kinds=["linkcraft.*.status"]) == 422
    assert status(kinds=[]) == 422
    assert status(severities=["bad"]) == 422
    assert client.post("/api/rules", json=critical_three_times(count=0)).status_code == 422
    assert client.post("/api/rules", json=critical_three_times(window_minutes=0)).status_code == 422
    assert status(kinds=["linkcraft.finding.*"]) == 201


def test_the_editors_check_diagrams_and_turn_the_simple_form(client):
    simple = client.post("/api/rules/simple", json={"simple": high()["simple"]}).json()
    assert simple["sentence"] == "pv ≥ 50 m3/h" and len(simple["diagram"]["nodes"]) == 3
    assert client.post("/api/rules/check", json={"diagram": simple["diagram"]}).json()["valid"]
    broken = {**simple["diagram"], "edges": []}
    checked = client.post("/api/rules/check", json={"diagram": broken}).json()
    assert checked["valid"] is False and checked["errors"]
    # A diagram drawn in Blocks is saved as it is.
    rule = {**high(), "editor": "blocks", "simple": None, "diagram": simple["diagram"]}
    made = make_rule(client, rule)
    assert made["editor"] == "blocks" and made["alarms"] == 1


CODE = "def check(inputs):\n    return inputs.pv > 50, 'pv is high'\n"


def python_rule() -> dict:
    diagram = client_diagram()
    return {**high(name="PV by Python"), "editor": "python", "simple": None, "diagram": diagram}


def client_diagram() -> dict:
    return {
        "version": 2,
        "nodes": [
            {"id": "v", "block": "alarm.value", "parameters": {"role": "pv"}, "label": "pv"},
            {"id": "p", "block": "alarm.python", "parameters": {"code": CODE}},
            {"id": "r", "block": "alarm.raise", "parameters": {}},
        ],
        "edges": [
            {"source": "v", "source_port": "value", "target": "p", "target_port": "values"},
            {"source": "p", "source_port": "condition", "target": "r", "target_port": "condition"},
        ],
    }


def test_only_administrators_write_python(runtime, fake, client):
    assert client.post("/api/rules", json=python_rule()).status_code == 403
    with client_for(runtime, fake, "admin") as admin:
        bad = python_rule()
        bad["diagram"]["nodes"][1]["parameters"]["code"] = (
            "import os\ndef check(inputs):\n    return 1"
        )
        assert admin.post("/api/rules", json=bad).status_code == 422
        made = make_rule(admin, python_rule())
    assert made["editor"] == "python"
    # An engineer changes its words, not its code.
    changed = {**python_rule(), "priority": "low", "base_updated_at": made["updated_at"]}
    assert client.put(f"/api/rules/{made['rule_id']}", json=changed).status_code == 200
    rewritten = python_rule()
    rewritten["diagram"]["nodes"][1]["parameters"]["code"] = CODE.replace("50", "60")
    assert client.put(f"/api/rules/{made['rule_id']}", json=rewritten).status_code == 403
    assert client.post("/api/run").json()["raised"] == 1
    alarm = client.get(f"/api/alarms/{made['rule_id']}").json()
    assert alarm["message"] == "pv is high"


def test_an_older_alarms_rules_become_simple_rules(tmp_path):
    from plantcraft_sdk.server.store import Database

    old = {
        "name": "FIC-1001 PV high",
        "assets": ["FIC-1001"],
        "role": "pv",
        "kind": "high",
        "limit": 50.0,
        "deadband": 0.5,
        "on_delay_seconds": 30,
        "priority": "high",
        "owner": "user:operator",
    }
    rule = from_legacy(old)
    [condition] = rule["simple"]["conditions"]
    assert condition["op"] == ">=" and condition["limit"] == 50.0
    assert condition["for_seconds"] == 30 and rule["where"]["assets"] == ["FIC-1001"]
    events = from_legacy(
        {"name": "Run failed", "kind": "events", "events": {"kinds": ["linkcraft.run.failed"]},
         "count": 2, "window_minutes": 30}
    )  # fmt: skip
    assert events["where"] == {"assets": [], "under": [], "anywhere": True}
    assert events["simple"]["conditions"][0]["count"] == 2
    verdict = from_legacy({"name": "Health", "kind": "verdict", "assets": ["FIC-1001"],
                           "result": "linkcraft:loop_health"})  # fmt: skip
    assert verdict["simple"]["conditions"][0]["event"]["kinds"] == ["linkcraft.status.changed"]
    # The store rewrites what it holds, once; a rule that does not fit stays, off.
    db = Database(tmp_path / "alarmcraft.sqlite3")
    with db.connect() as connection:
        connection.executescript(RuleStore.SCHEMA)
        for rule_id, config in (("pv-high", old), ("odd", {"name": "Odd", "kind": "high"})):
            connection.execute(
                "INSERT INTO rules VALUES (?, ?, ?, '2026-10-01', '', '2026-10-01', '')",
                (rule_id, config["name"], json.dumps(config)),
            )
    store = RuleStore(db)
    moved = store.get("pv-high")
    assert moved["editor"] == "simple" and moved["diagram"]["nodes"]
    odd = store.get("odd")
    assert odd["enabled"] is False


def test_viewers_see_incoming_but_do_not_start_rules(runtime, fake, client):
    make_rule(client, high())
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get("/api/incoming").status_code == 200
        assert viewer.get("/api/rules").status_code == 200
        assert viewer.get("/api/rules/from-event/1").status_code == 403
        assert viewer.post("/api/rules/try", json={"rule": high()}).status_code == 403


def test_the_assistant_creates_a_rule_on_one_signal(client):
    # "Help me create an alarm" (app.toml) proposes one signal's limit; it becomes a Simple rule.
    signal = PV
    body = {"name": "Pressure high", "signal_id": signal, "kind": "high", "limit": 12.5,
            "deadband": 0.2, "on_delay_seconds": 30, "priority": "high"}  # fmt: skip
    made = client.post("/api/rules/from-signal", json=body)
    assert made.status_code == 201, made.text
    rule = made.json()
    [condition] = rule["simple"]["conditions"]
    assert condition["value"]["signal"] == signal and condition["op"] == ">="
    assert condition["limit"] == 12.5 and condition["for_seconds"] == 30
    assert rule["editor"] == "simple" and rule["priority"] == "high"
    missing = client.post("/api/rules/from-signal", json={**body, "limit": None})
    assert missing.status_code == 422
    silent = client.post(
        "/api/rules/from-signal", json={**body, "name": "Quiet", "kind": "no_data"}
    )
    assert silent.status_code == 201
    assert silent.json()["simple"]["conditions"][0]["event"]["about"] == f"signal:{signal}"


def test_a_rule_from_an_opened_finding_hears_its_close(client, fake):
    # A finding opens with one kind and closes with another: the rule hears both.
    client.post("/api/run")
    _later(fake, 1)
    event = report(fake, "linkcraft.finding.opened", severity="warning")
    event.update(phase="start", key="FIC-1001|pv_variability")
    client.post("/api/run")
    found = client.get("/api/incoming").json()["events"][0]
    started = client.get(f"/api/rules/from-event/{found['id']}").json()
    [condition] = started["simple"]["conditions"]
    assert condition["test"] == "open"
    assert condition["event"]["kinds"] == ["linkcraft.finding.opened", "linkcraft.finding.closed"]
    assert client.post("/api/rules", json=started).status_code == 201


def test_a_new_plants_first_step_drafts_its_rules_switched_off(client, runtime, fake):
    body = {
        "assets": [{"id": "unit-100", "kind": "unit", "name": "Unit 100"}],
        "units": ["unit-100"],
    }
    done = client.post("/api/start/draft-rules", json=body)
    assert done.status_code == 200, done.text
    assert done.json()["counts"] == {"created": 2, "kept": 0}
    assert done.json()["open"] == "/alarm/rules"
    rules = {rule["name"]: rule for rule in client.get("/api/rules").json()}
    poor, silent = rules["Unit 100: loop in poor shape"], rules["Unit 100: signal without data"]
    assert not poor["enabled"] and not silent["enabled"]
    assert poor["where"]["under"] == ["unit-100"]
    kinds = [rule["simple"]["conditions"][0]["event"]["kinds"] for rule in (poor, silent)]
    assert kinds == [["linkcraft.status.changed"], ["histcraft.point.no_data"]]
    again = client.post("/api/start/draft-rules", json=body).json()
    assert again["counts"] == {"created": 0, "kept": 2}
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.post("/api/start/draft-rules", json=body).status_code == 403


def test_blocks_rules_become_simple_or_python():
    """Blocks retired (owner's review, 2026-10-27): a frozen-value drawing becomes a Simple rule
    ("did not change for 30 min"), value blocks into one Python block a Python rule, anything else
    stays drawn and keeps running."""

    from alarmcraft.alarms.rules import from_blocks

    def node(node_id, block, **parameters):
        return {
            "id": node_id,
            "block": block,
            "label": node_id,
            "x": 0,
            "y": 0,
            "parameters": parameters,
        }

    def wire(source, target, port="condition", target_port="condition"):
        return {"source": source, "source_port": port, "target": target, "target_port": target_port}

    frozen = {
        "name": "Frozen",
        "editor": "blocks",
        "where": {"under": ["U-100"]},
        "diagram": {
            "version": 2,
            "nodes": [
                node("pv", "alarm.value", role="pv"),
                node("changed", "alarm.changed"),
                node("still", "alarm.not"),
                node("long", "alarm.for", seconds=1800.0),
                node("alarm", "alarm.raise", clear_after_seconds=60.0),
            ],
            "edges": [
                wire("pv", "changed", "value", "value"),
                wire("changed", "still"),
                wire("still", "long"),
                wire("long", "alarm"),
            ],
        },
    }
    simple = from_blocks(frozen)
    assert simple["editor"] == "simple"
    condition = simple["simple"]["conditions"][0]
    assert condition["op"] == "unchanged" and condition["for_seconds"] == 1800.0
    assert condition["value"]["role"] == "pv" and simple["simple"]["clear_after_seconds"] == 60.0

    python = {
        **frozen,
        "diagram": {
            "version": 2,
            "nodes": [
                node("pv", "alarm.value", role="pv"),
                node("py", "alarm.python", code="x"),
                node("alarm", "alarm.raise"),
            ],
            "edges": [wire("pv", "py", "value", "values"), wire("py", "alarm")],
        },
    }
    assert from_blocks(python)["editor"] == "python"
    other = {
        **frozen,
        "diagram": {
            **frozen["diagram"],
            "nodes": frozen["diagram"]["nodes"][:4]
            + [node("x", "alarm.rate"), frozen["diagram"]["nodes"][4]],
        },
    }
    assert from_blocks(other) is None


def test_a_value_that_did_not_change_is_a_simple_condition(client):
    from alarmcraft.alarms.simple import SimpleLogic, to_diagram

    logic = SimpleLogic.model_validate(
        {
            "conditions": [
                {"input": "value", "value": {"role": "pv"}, "op": "unchanged", "for_seconds": 1800}
            ]
        }
    )
    assert "did not change" in logic.conditions[0].words()
    blocks = [node["block"] for node in to_diagram(logic)["nodes"]]
    assert blocks[:3] == ["alarm.value", "alarm.changed", "alarm.not"] and "alarm.for" in blocks


def test_a_permissive_that_does_not_hold_suppresses_the_alarm_by_design(client):
    # L3: FIC-1001's PV (about 55) is above 50, but the alarm is enabled only while TIC-1104's
    # PV is at or above 1000, which it never is: suppressed by design, not raised.
    rule = high(50.0)
    permissive = {"input": "value", "value": {"signal": "plantcraft:CPM.Loops.TIC-1104.PV"},
                  "op": ">=", "limit": 1000.0}  # fmt: skip
    rule["simple"] = {**rule["simple"], "enable_when": permissive, "enable_delay_seconds": 30}
    made = client.post("/api/rules", json=rule)
    assert made.status_code == 201, made.text
    assert "only while" in made.json()["sentence"]
    assert client.post("/api/run").json()["raised"] == 0
    [alarm] = made.json()["alarm_rows"] or client.get("/api/alarms").json()
    alarm = client.get(f"/api/alarms/{alarm['alarm_id']}").json()
    assert alarm["suppressed"] is True and alarm["active"] is False
    assert "Suppressed by design" in alarm["message"]
    # The permissive taken away: the same rule raises.
    rule["simple"] = {**rule["simple"], "enable_when": None}
    changed = client.put(f"/api/rules/{made.json()['rule_id']}",
                         json={**rule, "base_updated_at": made.json()["updated_at"]})  # fmt: skip
    assert changed.status_code == 200, changed.text
    assert client.post("/api/run").json()["raised"] == 1


def test_limits_by_grade_follow_the_grade_event(client, fake):
    # L8: FIC-1001's PV (about 55) is under the fixed limit (100), but over grade HD-5's 50;
    # the grade comes from the MES's grade change event.
    rule = high(100.0)
    rule["simple"]["conditions"][0]["grade_limits"] = [{"grade": "HD-5", "limit": 50.0},
                                                      {"grade": "LD-2", "limit": 90.0}]  # fmt: skip
    rule["simple"]["grade"] = {"source": "event", "kinds": ["mes.grade.changed"]}
    made = client.post("/api/rules", json=rule)
    assert made.status_code == 201, made.text
    assert "HD-5: 50, LD-2: 90 by grade" in made.json()["sentence"]
    assert client.post("/api/run").json()["raised"] == 0  # no grade yet: the fixed limit
    fake.links.events.append({
        "id": len(fake.links.events) + 1, "at": fake.now.isoformat(), "app": "mes",
        "kind": "mes.grade.changed", "subject": "line:L1", "actor": "user:system",
        "summary": "Grade HD-5", "refs": [], "payload": {"grade": "HD-5"},
        "severity": "info", "phase": "instant", "category": "process",
    })  # fmt: skip
    assert client.post("/api/run").json()["raised"] == 1
    [alarm] = client.get("/api/alarms").json()
    assert (
        "Grade HD-5: limit 50" in client.get(f"/api/alarms/{alarm['alarm_id']}").json()["message"]
    )
