"""Alarms' rules and alarms for notebooks and its examples (``Examples/Alarms``): served in the
suite's format and run as a person's notebook runs them."""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk import apptest
from plantcraft_sdk.notebooks import example_problems

from alarmcraft.notebook_examples import EXAMPLES
from tests.conftest import high, make_rule

ROOT = Path(__file__).resolve().parents[1]


def test_alarms_serves_its_rules_alarms_and_examples(client):
    make_rule(client, high())
    assert apptest.objects_problems(client, "", ROOT) == []
    assert example_problems(EXAMPLES) == []


def test_a_notebook_reads_a_rule_and_an_alarm_with_its_occurrences(client, runtime):
    rule = make_rule(client, high())
    runtime.replay.run(6, "operator")
    rules = client.get("/api/objects/rule").json()
    assert [item["id"] for item in rules["items"]] == [rule["rule_id"]]
    read = client.get(f"/api/objects/rule/{rule['rule_id']}").json()
    assert read["sentence"] and read["name"] == "FIC-1001 PV high"
    alarms = client.get("/api/objects/alarm").json()["items"]
    assert alarms, "the rule made its alarm"
    alarm = client.get(f"/api/objects/alarm/{alarms[0]['id']}").json()
    assert alarm["occurrences"] and alarm["status"]
    assert {"started_at", "ended_at", "limit"} <= set(alarm["occurrences"][0])
    assert client.get("/api/objects/alarm/nope").status_code == 404
    assert client.get("/api/objects/rule/nope").status_code == 404


def test_every_example_runs_as_a_notebook_runs_it(client, runtime, fake, tmp_path):
    # Near the PV (about 55), so six hours replayed give the study occurrences to count.
    make_rule(client, high(55.0))
    make_rule(client, high(50.0, name="FIC-1001 PV high (standing)"))
    assert runtime.replay.run(6, "operator")
    assert client.post("/api/run").status_code == 200  # live: each alarm knows its signal
    problems = apptest.run_examples(EXAMPLES, client, "", fake, root=ROOT, workdir=tmp_path)
    assert problems == [], "\n".join(problems)


def test_the_examples_say_so_when_there_is_nothing_to_study(client, fake, tmp_path):
    problems = apptest.run_examples(EXAMPLES, client, "", fake, root=ROOT, workdir=tmp_path)
    assert problems == [], "\n".join(problems)
