"""Executions by schedule (owner, 2026-10-24): schedules, then a schedule's subjects, then one
subject's latest result, the series its outputs are in and its past executions. Lists go by
name, never by status; status is a word beside each subject."""

from __future__ import annotations

import json

from tests.test_algorithms import _save, api, rt, suite_fake  # noqa: F401


def _scheduled(api, rt):  # noqa: F811
    _save(api)
    created = api.post(
        "/link/api/schedules",
        json={
            "name": "PV and valve",
            "profile_id": "pv_and_valve",
            "selector": {"mode": "list", "ids": ["tic-104", "fic-101"]},
            "cadence": "interval",
            "interval_minutes": 30,
            "lookback_minutes": 360,
        },
    ).json()
    for job_id in rt.jobs.run_schedule_now(created["schedule_id"], ["tic-104", "fic-101"]):
        rt.monitor.execute_job(job_id)
    return created


def test_executions_open_on_the_schedules_with_what_each_concluded(api, rt):  # noqa: F811
    schedule = _scheduled(api, rt)
    answer = api.get("/link/api/executions/groups").json()
    groups = {item["id"]: item for item in answer["groups"]}
    # The rounds first (each loop's own algorithm, Signal quality), then by name.
    assert [item["kind"] for item in answer["groups"]][:2] == ["round", "round"]
    mine = groups[schedule["schedule_id"]]
    assert mine["algorithm"]["name"] == "PV and valve" and mine["subjects"] == 2
    assert sum(mine["counts"].values()) == 2
    assert mine["path"] == f"/executions/{schedule['schedule_id']}"
    loops = groups["round-cpm"]
    assert loops["algorithm"]["name"] == "Each loop's own algorithm"
    assert loops["subjects"] >= 5 and sum(loops["counts"].values()) == loops["subjects"]
    assert answer["manual"]["id"] == "manual" and answer["manual"]["subjects"] == 0


def test_a_schedule_lists_its_subjects_by_name_with_a_word_for_their_status(api, rt):  # noqa: F811
    schedule = _scheduled(api, rt)
    found = api.get(f"/link/api/executions/groups/{schedule['schedule_id']}").json()
    assert [row["id"] for row in found["subjects"]] == ["fic-101", "tic-104"]  # by name
    frozen = found["subjects"][1]
    assert frozen["state"] == "alarm" and frozen["status_label"] == "Critical"
    loops = api.get("/link/api/executions/groups/round-cpm").json()["subjects"]
    names = [row["name"].lower() for row in loops]
    assert names == sorted(names)
    assert {row["status_label"] for row in loops} <= {
        "Normal",
        "Medium",
        "High",
        "Critical",
        "No health",
    }
    assert api.get("/link/api/executions/groups/nope").status_code == 404


def test_a_subject_shows_its_latest_result_its_series_and_its_past(api, rt):  # noqa: F811
    schedule = _scheduled(api, rt)
    base = f"/link/api/executions/groups/{schedule['schedule_id']}"
    found = api.get(f"{base}/tic-104").json()
    assert found["subject"]["id"] == "tic-104" and found["algorithm"]["id"] == "pv_and_valve"
    assert found["outputs"] and found["execution_id"]
    assert sorted(item["id"] for item in found["series"]) == [
        "app-linkcraft:tic-104.pv_and_valve.rule-if-then",
        "app-linkcraft:tic-104.pv_and_valve.stiction-screening",
    ]
    assert found["versions"] == "app-linkcraft:algorithm.pv_and_valve.version"
    assert len(found["executions"]) == 1 and found["executions"][0]["state"] == "alarm"
    assert found["detail_kept"] == 50
    assert api.get(f"{base}/lic-102").status_code == 404  # not in this schedule
    # The last run carries each block's verdict and what each wire carried (round 9, D22), with
    # its samples while it is one of the last runs (round 10), so a block's charts draw.
    last = found["last_run"]
    assert last["id"] == found["execution_id"] and last["at"] and last["version"] == 1
    assert last["blocks"] and last["wires"] and last["sampled"]
    assert any(
        len(port.get("t") or []) > 1
        for ports in last["wires"].values()
        for port in ports.values()
        if isinstance(port, dict)
    )
    assert found["executions"][0]["sampled"] and found["samples_kept"] == 10
    # The job keeps the last values only; the samples are kept apart.
    assert "samples" not in rt.jobs.get_job(last["id"])["summary"]
    loop = api.get("/link/api/executions/groups/round-cpm/fic-101").json()
    assert loop["series"][0]["id"] == "app-linkcraft:fic-101.flow_loop.health"
    assert loop["executions"] and loop["subject_path"] == "/loops/fic-101"
    asked = api.get(f"{base}/tic-104", params={"run": last["id"]}).json()["run"]
    assert asked["id"] == last["id"] and asked["wires"] == last["wires"]
    assert api.get(f"{base}/tic-104", params={"run": "gone"}).json()["run"] is None
    # A loop's round keeps no job: its last rounds open from their kept samples.
    assert loop["last_run"]["id"].startswith("fic-101@") and loop["last_run"]["blocks"]
    assert loop["last_run"]["version"] == 1 and loop["last_run"]["on"] == "loop"
    assert loop["last_run"]["sampled"] and loop["executions"][0]["id"] == loop["last_run"]["id"]
    round_run = api.get(
        "/link/api/executions/groups/round-cpm/fic-101", params={"run": loop["last_run"]["id"]}
    ).json()["run"]
    assert round_run["wires"] == loop["last_run"]["wires"] and round_run["blocks"]
    assert (
        api.get(
            "/link/api/executions/groups/round-cpm/fic-101", params={"run": "tic-104@2026"}
        ).json()["run"]
        is None
    )
    # Its window runs again with every sample, for the wires' full series.
    window = loop["last_run"]["window"]
    diagram = api.get("/link/api/algorithms/flow_loop").json()["diagram"]
    again = api.post(
        "/link/api/algorithms/test",
        json={"diagram": diagram, "loop_id": "fic-101", **window},
    ).json()
    assert again["source_end"][:16] == window["end"][:16] and again["trace"]
    # Each output on its own, not only the health that sums them (round 9, D11).
    methods = {item["key"]: item for item in loop["outputs"]}
    assert "stiction_screening" in methods and methods["stiction_screening"]["status_label"]
    assert all(item["state"] in {"ok", "warning", "alarm", "unknown"} for item in loop["outputs"])
    rt.run_signal_quality()
    signal = api.get("/link/api/executions/groups/round-signal_quality/fake:FIC-101.PV").json()
    checks = {item["key"]: item for item in signal["outputs"]}
    assert checks["sq_availability"]["state"] == "alarm" and checks["sq_frozen"]["state"] == "ok"


def test_runs_a_person_asked_for_are_in_manual_runs(api, rt):  # noqa: F811
    _save(api)
    job_id = rt.jobs.create_job(
        loop_id="fic-101",
        name="Try",
        kind="manual",
        profile_id="pv_and_valve",
        method_config={"profile_id": "pv_and_valve"},
        created_by="engineer",
    )
    rt.monitor.execute_job(job_id)
    manual = api.get("/link/api/executions/groups/manual").json()
    assert [row["id"] for row in manual["subjects"]] == ["fic-101"]
    one = api.get("/link/api/executions/groups/manual/fic-101").json()
    assert one["executions"][0]["id"] == job_id


def test_the_charts_read_only_links_own_series(api, rt):  # noqa: F811
    schedule = _scheduled(api, rt)
    found = api.get(f"/link/api/executions/groups/{schedule['schedule_id']}/tic-104").json()
    ids = [item["id"] for item in found["series"]] + [found["versions"]]
    answer = api.get("/link/api/executions/series", params={"signal": ids}).json()
    assert [item["signal"] for item in answer["series"]] == ids
    # A verdict that could not judge writes an empty point: that series may hold no value yet.
    assert sum(1 for item in answer["series"] if item["t"]) >= 2
    assert answer["series"][-1]["v"] == ["v1"]
    refused = api.get("/link/api/executions/series", params={"signal": ["plant:FIC-101.PV"]})
    assert refused.status_code == 422


def test_only_the_last_50_runs_per_subject_and_schedule_keep_their_detail(rt):  # noqa: F811
    ids = []
    for index in range(53):
        job_id = rt.jobs.create_job(
            loop_id="fic-101", name=f"Run {index}", kind="manual", created_by="engineer"
        )
        rt.jobs.complete_job(
            job_id,
            results=[{"method_id": "m", "status": "ok"}],
            summary={"verdict": {"status": "ok"}},
            config_snapshot={"x": 1},
            source_start=None,
            source_end=None,
        )
        ids.append(job_id)
    # The demo already ran fic-101 once, so 54 ended runs: the 4 oldest lose their detail.
    assert rt.jobs.prune_detail(keep=50) == 4
    oldest = rt.jobs.get_job(ids[0])
    assert oldest["summary"] == {"verdict": {"status": "ok"}}  # the summary stays
    assert rt.jobs.job_results(ids[0]) == [] and rt.jobs.job_results(ids[-1])
    assert rt.jobs.prune_detail(keep=50) == 0


def test_a_schedule_kept_on_an_old_protocol_id_shows_the_algorithm_that_replaced_it(api, rt):  # noqa: F811
    # schedules made before 0.3 keep ids such as "oscillation" (now Flow loop)
    schedule_id = rt.jobs.create_schedule(
        name="Oscillation watch",
        loop_id="fic-101",
        cadence="hourly",
        timezone="UTC",
        lookback_minutes=240,
        profile_id="oscillation",
        method_config={},
    )
    listed = {item["schedule_id"]: item for item in api.get("/link/api/schedules").json()}
    assert listed[schedule_id]["algorithm"] == {"id": "flow_loop", "name": "Flow loop"}
    groups = {item["id"]: item for item in api.get("/link/api/executions/groups").json()["groups"]}
    assert groups[schedule_id]["algorithm"]["name"] == "Flow loop"


RECORDED = {
    "verdict": {"status": "ok"},
    "recorded": [{"key": "model.y", "value": 2.0, "points": {"t": ["a", "b"], "v": [1.0, 2.0]}}],
}


def test_an_execution_keeps_its_recorded_series_without_their_points(rt):  # noqa: F811
    """The Historian keeps the points; an execution only each series' value (0.4.0 kept the
    whole window, tens of kB a run, until sorting the list overflowed SQLite's /tmp)."""

    job_id = rt.jobs.create_job(loop_id="u-1", name="Asset", kind="manual", work="asset")
    rt.jobs.finish(job_id, "completed", summary=RECORDED)
    kept = rt.jobs.get_job(job_id)["summary"]["recorded"]
    assert kept == [{"key": "model.y", "value": 2.0}]
    assert RECORDED["recorded"][0]["points"]  # the caller's summary is left as it was


def test_summaries_kept_by_0_4_0_are_thinned_a_batch_at_a_time(rt):  # noqa: F811
    ids = [
        rt.jobs.create_job(loop_id=f"u-{index}", name="Asset", kind="manual", work="asset")
        for index in range(3)
    ]
    with rt.jobs._lock, rt.jobs._connect() as connection:
        connection.executemany(
            "UPDATE analysis_jobs SET status = 'completed', summary_json = ? WHERE job_id = ?",
            [(json.dumps(RECORDED), job_id) for job_id in ids],
        )
    assert rt.jobs.thin_summaries(batch=2) == 2
    assert rt.jobs.thin_summaries(batch=2) == 1
    assert rt.jobs.thin_summaries(batch=2) == 0
    assert all("points" not in rt.jobs.get_job(job_id)["summary"]["recorded"][0] for job_id in ids)


def test_the_list_keeps_its_order_when_rows_are_read_after_the_ids(rt):  # noqa: F811
    for index in range(3):
        rt.jobs.create_job(loop_id="fic-101", name=f"Run {index}", kind="manual")
    rows = rt.jobs.list_jobs(limit=2000)
    moments = [row.get("started_at") or row["requested_at"] for row in rows]
    assert moments == sorted(moments, reverse=True)
    assert [row["job_id"] for row in rt.jobs.list_jobs(limit=2, offset=1)] == [
        row["job_id"] for row in rows[1:3]
    ]


def test_only_the_last_10_runs_of_a_subject_keep_their_samples(rt):  # noqa: F811
    store = rt.jobs.samples
    wires = {"n1": {"out": {"type": "series", "count": 3, "t": ["a", "b", "c"], "v": [1, 2, 3]}}}
    rows = [
        {
            "run_key": f"loop-a@2026-10-26T{hour:02d}:00",
            "scope": "round",
            "subject_id": "loop-a",
            "at": f"2026-10-26T{hour:02d}:00",
            "detail": {"wires": wires},
        }
        for hour in range(12)
    ]
    store.save(rows[:6])
    store.save(rows[6:])
    store.save([{**rows[0], "run_key": "other@x", "subject_id": "other"}])
    kept = store.kept("round", "loop-a")
    assert kept == {row["run_key"] for row in rows[2:]}
    assert (
        store.get(rows[-1]["run_key"]) == {"wires": wires} and store.get(rows[0]["run_key"]) is None
    )
    assert store.kept("round", "other") == {"other@x"}
