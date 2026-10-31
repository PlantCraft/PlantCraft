"""Assistant sections (prototype, E2): the model writes a part of a report from the results and
events about the assets an editor picked, and an editor's feedback becomes its next
requirements, kept version by version."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from dashcraft.reports import assistant as helper
from dashcraft.reports.model import Section
from tests.conftest import client_for
from tests.plant import NOW, publish_loop_health

SECTION = {
    "section_id": "ai",
    "kind": "assistant",
    "title": "This week in Unit 100",
    "assistant": {"asset_ids": ["unit-100"], "analyses": ["loops"]},
}


def report(**fields) -> dict:
    return {
        "name": "Weekly assistant report",
        "period": "7d",
        "schedule": {"every": "week", "at": "07:00", "weekday": "mon"},
        "sections": [SECTION],
        **fields,
    }


def finding(fake, subject: str, summary: str, hours_ago: float) -> None:
    fake.links.events.append(
        {
            "id": len(fake.links.events) + 1,
            "at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "app": "linkcraft",
            "kind": "linkcraft.finding.opened",
            "subject": subject,
            "actor": "app:linkcraft",
            "summary": summary,
            "refs": [],
            "payload": {},
            "severity": "warning",
        }
    )


def test_a_section_needs_assets_and_known_analyses():
    with pytest.raises(ValidationError):
        Section.model_validate({**SECTION, "assistant": None})
    with pytest.raises(ValidationError):
        Section.model_validate({**SECTION, "assistant": {"asset_ids": [], "analyses": ["loops"]}})
    with pytest.raises(ValidationError):
        Section.model_validate(
            {**SECTION, "assistant": {"asset_ids": ["a"], "analyses": ["weather"]}}
        )
    section = Section.model_validate(SECTION)
    assert section.assistant.requirements == helper.DEFAULT_REQUIREMENTS
    assert section.assistant.version == 1
    assert section.width == "full"


def test_scope_brings_the_assets_under_the_picked_ones():
    assets = [
        {"id": "plant", "parent_id": None},
        {"id": "u", "parent_id": "plant"},
        {"id": "l1", "parent_id": "u"},
        {"id": "l2", "parent_id": "u"},
        {"id": "other", "parent_id": "plant"},
    ]
    spec = helper.AssistantSpec(asset_ids=["u"], analyses=["loops"])
    assert [a["id"] for a in helper.scope(assets, spec)] == ["u", "l1", "l2"]
    alone = helper.AssistantSpec(asset_ids=["u"], analyses=["loops"], children=False)
    assert [a["id"] for a in helper.scope(assets, alone)] == ["u"]


def test_the_model_writes_the_section_from_the_facts_in_scope(client, fake, runtime):
    publish_loop_health(fake)
    finding(fake, "asset:fic-101", "Oscillation found, period 4 min", hours_ago=30)
    finding(fake, "asset:fic-101", "Old finding, outside the week", hours_ago=24 * 9)
    fake.links.llm_answer = "```markdown\n# Summary\nFIC-101 oscillates.\n```"
    created = client.post("/dash/api/reports", json=report())
    assert created.status_code == 201, created.text
    report_id = created.json()["report_id"]

    made = client.post(f"/dash/api/reports/{report_id}/pdf")
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "done"
    assert made.json()["problems"] == 0

    [call] = fake.links.llm_calls
    assert call["use"] == "report-write"
    question = call["messages"][-1]["content"]
    facts = json.loads(question.split("FACTS:\n", 1)[1])
    assert {a["asset"] for a in facts["assets"]} >= {"Unit 100", "FIC-101"}
    assert [r["asset"] for r in facts["results"]][0] == "FIC-101"  # worst first
    assert [e["summary"] for e in facts["events"]] == ["Oscillation found, period 4 min"]
    assert "REQUIREMENTS:\n- Start with three" in question

    section = client.get(f"/dash/api/reports/{report_id}/sections/ai").json()
    written = section["data"]["written"]
    assert written["text"] == "## Summary\nFIC-101 oscillates."  # fence gone, heading lowered
    assert written["version"] == 1

    exported = client.get(f"/dash/api/reports/{report_id}/export/md")
    assert exported.status_code == 200
    assert "FIC-101 oscillates." in exported.text
    assert len(fake.links.llm_calls) == 1  # a download reads what was written, no new call


def test_no_model_leaves_the_reason_in_the_section(client, fake):
    fake.links.llm_answer = None  # off, as app.toml ships it
    report_id = client.post("/dash/api/reports", json=report()).json()["report_id"]
    made = client.post(f"/dash/api/reports/{report_id}/pdf").json()
    assert made["status"] == "done"
    assert made["problems"] == 1


def test_feedback_proposes_requirements_the_editor_applies(client, fake):
    publish_loop_health(fake)
    answers = iter(["Long text about every loop.", "- Only loops in warning.\n- Max 5 lines."])
    fake.links.llm_answer = lambda call: next(answers)
    report_id = client.post("/dash/api/reports", json=report()).json()["report_id"]
    client.post(f"/dash/api/reports/{report_id}/pdf")

    tuned = client.post(
        f"/dash/api/reports/{report_id}/assistant/ai/feedback",
        json={"feedback": "Too long. Only the loops that need work."},
    )
    assert tuned.status_code == 200, tuned.text
    body = tuned.json()
    assert body["requirements"].startswith("- Only loops in warning.")
    assert body["warnings"] == []
    # Only a proposal: the report keeps version 1 until the editor applies it.
    kept = client.get(f"/dash/api/reports/{report_id}").json()["sections"][0]["assistant"]
    assert kept["version"] == 1
    call = fake.links.llm_calls[-1]
    assert call["use"] == "report-tune"
    assert "Long text about every loop." in call["messages"][-1]["content"]
    assert "Too long." in call["messages"][-1]["content"]

    applied = client.put(
        f"/dash/api/reports/{report_id}/assistant/ai/requirements",
        json={"requirements": body["requirements"], "feedback": body["feedback"]},
    )
    assert applied.json()["version"] == 2
    saved = client.get(f"/dash/api/reports/{report_id}").json()
    assistant = saved["sections"][0]["assistant"]
    assert assistant["version"] == 2
    assert assistant["requirements"] == body["requirements"]

    history = client.get(f"/dash/api/reports/{report_id}/assistant/ai").json()
    assert [v["version"] for v in history["versions"]] == [1, 2]
    assert history["versions"][1]["feedback"] == "Too long. Only the loops that need work."
    assert len(history["drafts"]) == 1

    back = client.put(
        f"/dash/api/reports/{report_id}/assistant/ai/requirements",
        json={"requirements": history["versions"][0]["requirements"]},
    )
    assert back.json()["version"] == 3


def test_feedback_is_for_editors_and_needs_a_model(client, fake, runtime):
    report_id = client.post("/dash/api/reports", json=report()).json()["report_id"]
    with client_for(runtime, fake, "operator") as viewer:
        refused = viewer.post(
            f"/dash/api/reports/{report_id}/assistant/ai/feedback", json={"feedback": "x"}
        )
        assert refused.status_code == 403
    fake.links.llm_answer = None
    answer = client.post(
        f"/dash/api/reports/{report_id}/assistant/ai/feedback", json={"feedback": "x"}
    )
    assert answer.status_code == 409


def test_the_model_proposes_the_assets_from_a_description(client, fake):
    fake.links.llm_answer = json.dumps(
        {"asset_ids": ["fic-101", "made-up"], "analyses": ["loops", "nope"], "why": "flow loop"}
    )
    answer = client.post(
        "/dash/api/report-assistant/scope", json={"description": "The feed flow loop"}
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["asset_ids"] == ["fic-101"]
    assert body["dropped"] == ["made-up"]
    assert body["analyses"] == ["loops"]


def test_the_analyses_list_for_the_checkboxes(client):
    found = client.get("/dash/api/report-analyses").json()
    assert [a["id"] for a in found] == ["loops", "signals", "alarms", "collection"]


def test_a_proposal_that_copies_the_data_is_flagged():
    assert helper.requirement_problems("- Start with the worst loops.") == []
    [problem] = helper.requirement_problems("- Mechanical: FIC-1003, 0 alarms.")
    assert "FIC-1003" in problem


def test_facts_are_counted_and_ranked_per_asset():
    facts = {
        "results": [
            {"asset": "A-1", "status": "warning", "score": 60, "summary": "noise"},
            {"asset": "B-2", "status": "alarm", "score": 40, "summary": "oscillation"},
            {"asset": "C-3", "status": "alarm", "score": 35, "summary": "saturated"},
            {"asset": "D-4", "status": "ok", "score": 95},
        ]
    }
    events = [
        {"asset": "B-2", "kind": "alarmcraft.alarm.raised", "severity": "critical"},
        {"asset": "B-2", "kind": "alarmcraft.alarm.raised", "severity": "warning"},
        {"asset": "A-1", "kind": "linkcraft.finding.opened"},
    ]
    ranked = helper.by_asset(facts, events)
    assert [r["asset"] for r in ranked] == ["C-3", "B-2", "A-1", "D-4"]
    assert ranked[1]["alarms"] == 2 and ranked[1]["critical_alarms"] == 1
    assert ranked[2]["findings_opened"] == 1
    assert ranked[3]["problems"] == []


def test_a_tag_the_facts_never_name_is_flagged():
    facts = {"assets": [{"asset": "FIC-101"}], "results": [], "events": []}
    assert helper.ungrounded("FIC-101 is fine; PIC-999 oscillates.", facts) == ["PIC-999"]
    text = helper.section_text("Week", "PIC-999 oscillates.", facts)
    assert "PIC-999, which the facts it was given do not" in text
    assert "Check:" not in helper.section_text("Week", "FIC-101 is fine.", facts)
