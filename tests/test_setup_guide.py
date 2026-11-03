# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""The setup guide (plantcraft/api/setup_guide.py, docs/setup-guide.md): each step's state comes from
the installation itself, the robot's works propose and the guide's routes apply as the person,
and only administrators see it."""

from __future__ import annotations

from plantcraft.api import setup_guide
from plantcraft.assistant_works import WorkRegistry
from tests.test_assistant_chat import LOCAL
from tests.test_collaboration import _person, signed  # noqa: F401


def _steps(client) -> dict[str, dict]:
    found = client.get("/api/setup-guide")
    assert found.status_code == 200, found.text
    return {step["id"]: step for step in found.json()["steps"]}


def test_the_guide_starts_with_the_model_and_moves_on_by_itself(signed):
    guide = signed.get("/api/setup-guide").json()
    assert guide["ready"] is False and guide["current"] == "model" and guide["hidden"] is False
    # Documents is not installed here: its step is left out.
    assert "documents" not in {step["id"] for step in guide["steps"]}
    assert signed.put("/api/language-model", json=LOCAL).status_code == 200
    guide = signed.get("/api/setup-guide").json()
    assert guide["ready"] is True and guide["current"] == "basics"
    steps = {step["id"]: step for step in guide["steps"]}
    assert steps["model"]["state"] == "done"
    assert steps["basics"]["facts"]["time_zone_chosen"] is False
    assert steps["basics"]["work"] == "processcraft:guide-basics"


def test_the_basics_card_sets_the_zone_and_the_persons_language(signed):
    applied = signed.post(
        "/api/setup-guide/basics", json={"time_zone": "America/Sao_Paulo", "language": "pt-BR"}
    )
    assert applied.status_code == 200, applied.text
    assert signed.get("/api/setup/installation").json()["time_zone"] == "America/Sao_Paulo"
    assert signed.get("/api/me/preferences").json()["language"] == "pt-BR"
    assert _steps(signed)["basics"]["state"] == "done"
    bad = signed.post("/api/setup-guide/basics", json={"time_zone": "Mars/Olympus"})
    assert bad.status_code == 422
    assert (
        signed.post(
            "/api/setup-guide/basics", json={"time_zone": "UTC", "language": "xx"}
        ).status_code
        == 422
    )


def test_marks_skip_and_come_back(signed):
    assert signed.post("/api/setup-guide/steps/email", json={"state": "skipped"}).json()
    assert _steps(signed)["email"]["state"] == "skipped"
    assert signed.post("/api/setup-guide/steps/email", json={"state": None}).status_code == 200
    assert _steps(signed)["email"]["state"] in {"todo", "current"}
    assert signed.post("/api/setup-guide/steps/nothing", json={"state": "done"}).status_code == 404
    actions = [row["action"] for row in signed.app.state.runtime.workspace.audit.list(limit=20)]
    assert "setup_guide.mark" in actions


def test_a_source_that_does_not_answer_is_kept_with_why(signed):
    made = signed.post(
        "/api/setup-guide/connection",
        json={"name": "Plant OPC UA", "kind": "opcua", "endpoint": "opc.tcp://127.0.0.1:1/x"},
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["id"] and body["test"]["ok"] is False and body["test"]["message"]
    step = _steps(signed)["connection"]
    assert step["state"] != "done"
    assert step["facts"]["sources"][0]["name"] == "Plant OPC UA"
    assert step["facts"]["sources"][0]["connected"] is False


def test_people_count_only_the_plants_team(signed):
    before = _steps(signed)["people"]
    assert before["state"] != "done"
    _person(signed, "joana")
    assert _steps(signed)["people"]["state"] == "done"


def test_only_administrators_see_the_guide_and_hiding_is_each_ones(signed):
    viewer = _person(signed, "rita", level="viewer")
    assert viewer.get("/api/setup-guide").status_code == 403
    assert viewer.post("/api/setup-guide/basics", json={"time_zone": "UTC"}).status_code == 403
    hidden = signed.post("/api/setup-guide/hide", json={"hidden": True}).json()
    assert hidden["hidden"] is True
    assert signed.post("/api/setup-guide/hide", json={"hidden": False}).json()["hidden"] is False


def test_each_step_has_its_work_and_the_create_works_point_at_real_routes():
    works = {work.spec.id: work for work in WorkRegistry().all()}
    for step in setup_guide.steps():
        if step.id == "model":
            continue  # before a model the robot cannot talk
        assert f"guide-{step.id}" in works, step.id
    assert works["guide-basics"].spec.create == "/api/setup-guide/basics"
    assert works["guide-connection"].spec.create == "/api/setup-guide/connection"
    assert works["guide-people"].spec.create == "/api/users"
    # Every guide work is on the guide's page and only for administrators where it writes.
    for key, work in works.items():
        if key.startswith("guide-"):
            assert work.spec.pages == ["setup-guide"]
            if work.spec.kind == "create":
                assert work.spec.level == "admin"


def test_missions_come_after_the_setup_and_count_what_the_person_did(signed):
    guide = signed.get("/api/setup-guide").json()
    ids = [item["id"] for item in guide["missions"]]
    # Only the apps listed here (Alarms is not): the platform's own missions and theirs.
    assert ids == ["ask", "analytics", "dashboard", "notebook"] and guide["missions_done"] == 0
    audit = signed.app.state.runtime.workspace.audit
    # The guide's own chat reading help is not a question about the plant.
    audit.record("admin", "assistant.tool", "tool:read_help", {}, app_id="processcraft")
    assert signed.get("/api/setup-guide").json()["missions_done"] == 0
    audit.record("admin", "assistant.tool", "tool:show_chart", {}, app_id="processcraft")
    found = signed.get("/api/setup-guide").json()
    assert found["missions_done"] == 1
    assert {item["id"]: item["done"] for item in found["missions"]}["ask"] is True
    # Someone else's notebook is not this person's mission.
    audit.record("ana", "notebooks.create", "notebook:1", {}, app_id="processcraft")
    assert signed.get("/api/setup-guide").json()["missions_done"] == 1


def test_each_mission_has_its_work():
    works = {work.spec.id for work in WorkRegistry().all()}
    for mission in setup_guide.missions():
        assert f"mission-{mission.id}" in works
