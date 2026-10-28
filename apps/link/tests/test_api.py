"""The HTTP API: who may do what, loop settings, reports, runs and the audit trail."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from linkcraft.api.app import create_app, ui_folder
from tests.conftest import client_for
from tests.plant import sid

NEW_LOOP = {
    "loop_id": "FIC-900",
    "name": "Test loop",
    "area": "Area B",
    "signals": {"pv": sid("FIC-101.PV"), "sp": sid("FIC-101.SP"), "op": sid("FIC-101.OP")},
    "profile_id": "tracking",
}


def _actions(fake) -> list[str]:
    return [entry["action"] for entry in fake.audit_log]


def test_health_and_root_redirect(runtime):
    with TestClient(create_app(runtime)) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/link/healthz").json()["status"] == "ok"
        home = client.get("/", follow_redirects=False)
        assert home.status_code == 307 and home.headers["location"] == "/link/"


def test_the_api_needs_a_processcraft_token_with_access(runtime, fake):
    with TestClient(create_app(runtime), raise_server_exceptions=False) as anonymous:
        assert anonymous.get("/link/api/loops").status_code == 401
    with client_for(runtime, fake, "outsider") as outsider:
        assert outsider.get("/link/api/loops").status_code == 403
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get("/link/api/loops").status_code == 200
        assert viewer.post("/link/api/loops", json=NEW_LOOP).status_code == 403
        assert viewer.post("/link/api/round").status_code == 403


@pytest.mark.skipif(ui_folder() is None, reason="interface not built")
def test_a_browser_without_a_token_is_sent_to_sign_in(runtime):
    with TestClient(create_app(runtime)) as client:
        page = client.get("/link/", headers={"Accept": "text/html"}, follow_redirects=False)
        assert page.status_code == 303
        assert "login" in page.headers["location"]


def test_me_names_the_user(client):
    me = client.get("/link/api/me").json()
    assert me["username"] == "engineer" and me["can_edit"] is True


def test_me_role_shows_an_admin_as_admin(runtime, fake):
    # An admin's app access is "editor" in the token; the user menu shows the level.
    roles = {}
    for username in ("admin", "engineer", "operator"):
        with client_for(runtime, fake, username) as client:
            roles[username] = client.get("/link/api/me").json()["role"]
    assert roles == {"admin": "admin", "engineer": "editor", "operator": "viewer"}


def test_loops_list_shows_pending_loops_before_the_first_round(client, runtime):
    runtime.sync_loops()
    rows = client.get("/link/api/loops").json()
    assert {row["loop_id"] for row in rows} >= {"fic-101", "lic-102"}
    assert all(row["status"] == "pending" for row in rows)


def test_loop_page_carries_the_diagnosis_and_trends(client, analysed):
    body = client.get("/link/api/loops/lic-102").json()
    assert body["origin"] == "processcraft"
    assert body["summary"]["status"] in {"critical", "high"}
    methods = {item["method_id"]: item for item in body["results"]}
    assert methods["oscillation_autocorrelation"]["status"] == "bad"
    assert body["series"] and {"pv", "sp", "op"} <= set(body["series"][0])
    assert client.get("/link/api/loops/nope").status_code == 404


def test_user_defined_loops_are_validated_against_processcraft_and_audited(client, fake):
    created = client.post("/link/api/loops", json=NEW_LOOP)
    assert created.status_code == 201, created.text
    assert created.json()["origin"] == "user"
    assert client.post("/link/api/loops", json=NEW_LOOP).status_code == 409

    unknown = {**NEW_LOOP, "loop_id": "FIC-901", "signals": {"pv": "NOPE.PV"}}
    answer = client.post("/link/api/loops", json=unknown)
    assert answer.status_code == 422 and "NOPE.PV" in answer.json()["detail"]

    patched = client.patch("/link/api/loops/FIC-900", json={"name": "Renamed", "enabled": False})
    assert patched.status_code == 200 and patched.json()["loop"]["name"] == "Renamed"
    assert client.delete("/link/api/loops/FIC-900").status_code == 204
    assert {entry.get("app") for entry in fake.audit_log} == {"linkcraft"}
    assert _actions(fake)[-3:] == [
        "linkcraft.loop.created",
        "linkcraft.loop.updated",
        "linkcraft.loop.deleted",
    ]


def test_processcraft_loops_keep_their_name_and_signals_there(client, runtime):
    runtime.sync_loops()
    assert client.patch("/link/api/loops/fic-101", json={"name": "x"}).status_code == 409
    assert client.delete("/link/api/loops/fic-101").status_code == 409
    changed = client.patch(
        "/link/api/loops/fic-101", json={"profile_id": "tracking", "criticality": "high"}
    )
    assert changed.status_code == 200
    assert changed.json()["loop"]["profile_id"] == "tracking"
    bad = client.patch(
        "/link/api/loops/fic-101",
        json={"method_parameters": {"pv_variability": {"variability_tolerance": -1}}},
    )
    assert bad.status_code == 422
    unknown = client.patch("/link/api/loops/fic-101", json={"method_parameters": {"nope": {}}})
    assert unknown.status_code == 422


def test_sync_through_the_api_uses_the_users_token(client):
    result = client.post("/link/api/loops/sync").json()
    assert result["status"] == "ok" and result["found"] == 5


def test_a_new_plants_first_step_monitors_the_loops_it_imported(client, runtime, fake):
    body = {"import_id": "1", "assets": [{"id": "fic-101", "kind": "loop"}, {"id": "U-1"}]}
    done = client.post("/link/api/start/analyze-loops", json=body)
    assert done.status_code == 200, done.text
    answer = done.json()
    assert answer["counts"] == {"loops": 1, "rounds": 1} and answer["open"] == "/link/results"
    assert "linkcraft.round.started" in _actions(fake)
    # Taken again while that round waits: the loops are read again, no second round.
    again = client.post("/link/api/start/analyze-loops", json=body).json()
    assert again["counts"] == {"loops": 1, "rounds": 0}
    none = client.post("/link/api/start/analyze-loops", json={"assets": [{"id": "U-1"}]}).json()
    assert none["counts"] == {"loops": 0, "rounds": 0}
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.post("/link/api/start/analyze-loops", json=body).status_code == 403


def test_loop_and_weekly_reports_are_pdfs(client, analysed):
    loop = client.get("/link/api/loops/pic-103/report.pdf")
    assert loop.status_code == 200 and loop.content.startswith(b"%PDF")
    assert "loop-pic-103.pdf" in loop.headers["content-disposition"]
    weekly = client.get("/link/api/reports/weekly.pdf")
    assert weekly.status_code == 200 and weekly.content.startswith(b"%PDF")


def test_a_loop_report_before_any_round_still_renders(client, runtime):
    runtime.sync_loops()
    answer = client.get("/link/api/loops/fic-101/report.pdf")
    assert answer.status_code == 200 and answer.content.startswith(b"%PDF")


def test_round_from_the_api_and_status(client, fake):
    assert client.post("/link/api/round").status_code == 202
    status = client.get("/link/api/status").json()
    assert status["service_key"] is True
    assert "linkcraft.round.started" in _actions(fake)


def test_a_run_reads_through_processcraft_and_completes(client, analysed):
    job = client.post(
        "/link/api/jobs",
        json={"loop_id": "lic-102", "name": "Check", "lookback_minutes": 120},
    )
    assert job.status_code == 201, job.text
    done = analysed.monitor.execute_job(job.json()["job_id"])
    assert done["status"] == "completed", done.get("error")
    detail = client.get(f"/link/api/jobs/{done['job_id']}").json()
    assert detail["status"] == "completed" and detail["results"]
    assert client.post("/link/api/jobs", json={"loop_id": "nope", "name": "x"}).status_code == 404


def test_schedules_are_created_listed_and_removed(client, analysed, fake):
    created = client.post(
        "/link/api/schedules",
        json={
            "name": "Morning",
            "cadence": "daily",
            "time_local": "07:30",
            "lookback_minutes": 60,
            "selector": {"mode": "all"},
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule_id"]
    listed = {item["schedule_id"] for item in client.get("/link/api/schedules").json()}
    assert {schedule_id, "round-cpm"} <= listed
    paused = client.patch(f"/link/api/schedules/{schedule_id}", json={"enabled": False})
    assert paused.status_code == 200
    assert client.delete(f"/link/api/schedules/{schedule_id}").status_code == 204
    assert "linkcraft.schedule.created" in _actions(fake)


def test_method_catalog_lists_signal_checks_then_the_gate(client):
    groups = client.get("/link/api/method-groups").json()
    assert [item["group_id"] for item in groups] == ["signal_quality", "data_quality", "cpm"]
    assert groups[0]["role"] == "signal" and groups[0]["method_count"] == 8
    assert groups[1]["role"] == "gate"
    methods = client.get("/link/api/methods").json()
    assert len(methods) == 18 + 8
    signal = [item for item in methods if item["application"] == "signal_quality"]
    assert {item["applies_to"] for item in signal} == {"signal"}
    assert all(item["method_id"].startswith("sq_") for item in signal)
    assert {item["method_id"] for item in methods if item["gate"]} == {
        "dq_availability",
        "dq_value_integrity",
        "dq_statistics",
    }
    source = client.get("/link/api/methods/stiction_screening/source").json()
    assert "def run" in source["source"] and source["editable"] is False


def test_method_defaults_need_an_admin(runtime, fake):
    body = {"parameters": {"variability_tolerance": 3}, "description": "Tighter tolerance"}
    with client_for(runtime, fake, "engineer") as engineer:
        assert (
            engineer.put("/link/api/methods/pv_variability/defaults", json=body).status_code == 403
        )
    with client_for(runtime, fake, "admin") as admin:
        saved = admin.put("/link/api/methods/pv_variability/defaults", json=body)
        assert saved.status_code == 200
        assert saved.json()["configured_defaults"]["variability_tolerance"] == 3


def test_saving_defaults_is_a_new_version_with_what_changed(runtime, fake):
    """Owner, 2026-10-27: every save of the defaults is a version with a description; old ones
    can be deleted, never the one in use."""

    url = "/link/api/methods/pv_variability/defaults"
    with client_for(runtime, fake, "admin") as admin:
        # No description, no save.
        refused = admin.put(url, json={"parameters": {"variability_tolerance": 3}})
        assert refused.status_code == 422
        for value, note in ((3, "Tighter"), (4, "Looser")):
            answer = admin.put(
                url, json={"parameters": {"variability_tolerance": value}, "description": note}
            )
            assert answer.status_code == 200, answer.text
        versions = admin.get(f"{url}/versions").json()
        assert [(item["number"], item["description"]) for item in versions] == [
            (2, "Looser"),
            (1, "Tighter"),
        ]
        assert versions[0]["current"] and versions[0]["saved_by"] == "admin"
        assert versions[1]["parameters"]["variability_tolerance"] == 3
        assert admin.delete(f"{url}/versions/2").status_code == 409
        assert admin.delete(f"{url}/versions/1").status_code == 200
        assert [item["number"] for item in admin.get(f"{url}/versions").json()] == [2]
        assert admin.delete(f"{url}/versions/1").status_code == 404
        assert admin.get("/link/api/methods/nope/defaults/versions").status_code == 404
    with client_for(runtime, fake, "engineer") as engineer:
        assert engineer.delete(f"{url}/versions/2").status_code == 403


def test_signals_search_reads_processcraft(client):
    found = client.get("/link/api/signal-search", params={"q": "FIC-101"}).json()
    assert {item["id"] for item in found} >= {sid("FIC-101.PV")}


def test_the_suite_monitor_reads_linkcraft_metrics(runtime, fake):
    with client_for(runtime, fake, "admin") as admin:
        answer = admin.get("/link/api/ops/metrics")
    assert answer.status_code == 200, answer.text
    assert answer.json()["app"] == "linkcraft"
    with client_for(runtime, fake, "engineer") as engineer:
        assert engineer.get("/link/api/ops/metrics").status_code == 403


def test_unknown_api_paths_are_404(client):
    assert client.get("/link/api/nothing/here").status_code == 404
