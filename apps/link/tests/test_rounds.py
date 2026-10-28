"""A monitoring round against PlantCraft (the SDK's fake) finds the known faults."""

from __future__ import annotations

import pandas as pd
import pytest

from linkcraft.config import LoopConfig
from tests.conftest import make_runtime
from tests.plant import NOW, assets, make_fake, sid


def _results(runtime, loop_id: str) -> dict[str, dict]:
    payload = runtime.monitor.loop_payload(loop_id)
    return {item["method_id"]: item for item in payload["results"]}


def test_loops_come_from_processcraft_loop_assets(runtime):
    result = runtime.sync_loops()
    assert result["status"] == "ok"
    assert result["added"] == 5
    loop = runtime.loops.get_loop("fic-101")
    assert loop.name == "FIC-101"
    assert loop.service == "Feed flow"
    assert loop.area == "Area A"
    assert loop.unit == "Unit 100"
    assert loop.signals.pv == sid("FIC-101.PV") and loop.signals.mode == sid("FIC-101.MODE")
    assert runtime.loops.origins()["fic-101"] == "processcraft"


def test_a_resync_keeps_cpm_settings_and_disables_removed_assets(runtime, fake):
    runtime.sync_loops()
    loop = runtime.loops.get_loop("lic-102")
    runtime.loops.save_loop(loop.model_copy(update={"profile_id": "tracking"}), actor="engineer")

    remaining = [item for item in assets() if item["id"] != "fic-105"]
    for item in remaining:
        if item["id"] == "lic-102":
            item["attributes"] = {"description": "Drum level (renamed)"}
    fake.assets = remaining
    result = runtime.sync_loops()
    assert result["status"] == "ok"
    assert result["disabled"] == 1
    kept = runtime.loops.get_loop("lic-102")
    assert kept.service == "Drum level (renamed)"
    assert kept.profile_id == "tracking"
    gone = runtime.loops.get_loop("fic-105")
    assert gone.enabled is False and gone.metadata.get("asset_missing")


def test_the_round_finds_each_known_fault(analysed):
    statuses = {row["loop_id"]: row["status"] for row in analysed.monitor.overview_rows()}
    assert statuses["fic-101"] == "normal"
    assert statuses["tic-104"] == "no_data"
    for loop_id in ("lic-102", "pic-103", "fic-105"):
        assert statuses[loop_id] in {"critical", "high"}, loop_id

    assert _results(analysed, "lic-102")["oscillation_autocorrelation"]["status"] == "bad"
    assert _results(analysed, "pic-103")["op_saturation_fraction"]["status"] == "bad"
    assert _results(analysed, "fic-105")["stiction_screening"]["status"] == "bad"
    healthy = _results(analysed, "fic-101")
    assert healthy["oscillation_autocorrelation"]["status"] == "ok"
    assert healthy["op_saturation_fraction"]["status"] == "ok"


def test_the_round_ends_at_the_last_sample_processcraft_has(analysed):
    header = analysed.monitor.snapshot
    end = pd.Timestamp(header["source_end"])
    assert end == pd.Timestamp(NOW).tz_convert(None)


def test_mode_numbers_reach_the_methods_as_states(analysed):
    manual = _results(analysed, "fic-101")["manual_mode_fraction"]
    assert manual["status"] == "ok"
    assert manual["metrics"]["manual_fraction"] == pytest.approx(0.0)


def test_mode_labels_reach_manual_mode_fraction(tmp_path):
    """A mode recorded as text ("AUTO"/"MAN", API v1 ``kind: text``) is read as states."""

    fake = make_fake()
    index = fake.series_data[sid("FIC-101.PV")].index
    labels = pd.Series("AUTO", index=index, dtype=object)
    labels.iloc[: len(index) // 4] = "MAN"
    fake.series_data[sid("FIC-101.MODE")] = labels
    assert fake.client().signal(sid("FIC-101.MODE"))["kind"] == "text"
    runtime = make_runtime(tmp_path, fake)
    try:
        runtime.run_round()
        manual = _results(runtime, "fic-101")["manual_mode_fraction"]
        assert manual["metrics"]["manual_fraction"] == pytest.approx(0.25, abs=0.01)
        assert manual["status"] != "ok"
    finally:
        runtime.shutdown()


def test_background_work_without_an_app_key_says_so(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake, app_key=False)
    try:
        runtime.loops.save_loop(
            LoopConfig(loop_id="x", name="x", signals={"pv": sid("FIC-101.PV")}),
            actor="engineer",
            origin="user",
        )
        snapshot = runtime.run_round()
        assert snapshot["status"] == "error"
        assert "app key" in snapshot["error"]
    finally:
        runtime.shutdown()


def test_the_first_round_leaves_one_completed_baseline_job_per_loop(analysed):
    jobs = analysed.jobs.list_jobs(kinds={"baseline"})
    assert sorted(job["loop_id"] for job in jobs) == sorted(
        loop.loop_id for loop in analysed.loops.list_loops(enabled_only=True)
    )
    job = next(item for item in jobs if item["loop_id"] == "lic-102")
    assert job["status"] == "completed" and job["created_by"] == "System"
    assert job["started_at"] and job["completed_at"] and job["summary"]["status"]
    full = analysed.jobs.get_job(job["job_id"])
    assert full["config_snapshot"]["loop"]["loop_id"] == "lic-102"
    methods = {item["method_id"] for item in analysed.jobs.job_results(job["job_id"])}
    assert "oscillation_autocorrelation" in methods
    analysed.monitor.ensure_initial_jobs()  # a second call adds none
    assert len(analysed.jobs.list_jobs(kinds={"baseline"})) == len(jobs)


def test_each_known_fault_gets_its_likely_cause_first(analysed):
    from linkcraft.report.causes import likely_causes

    def first(loop_id):
        results = analysed.monitor.loop_payload(loop_id)["results"]
        causes = likely_causes(results)
        return causes[0]["cause_id"] if causes else None

    assert first("fic-105") == "stiction"
    assert first("pic-103") == "saturation"
    assert first("lic-102") in {"aggressive_tuning", "external_disturbance"}
    assert first("fic-101") is None
