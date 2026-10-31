"""What the Signal quality protocol publishes in PlantCraft (app standard, section 6):
results, derived series, runs and its schedule."""

from __future__ import annotations

import logging

import pytest
from plantcraft_sdk.refs import parse_ref, signal_ref
from plantcraft_sdk.testing import FakeResponse

from linkcraft.signals.publish import asset_result, quality_points, signal_result
from tests.conftest import client_for
from tests.conftest import make_signal_runtime as make_runtime
from tests.signal_plant import EXPECTED
from tests.signal_plant import make_signal_fake as make_fake

ROUTES = ("/api/v1/results", "/api/v1/runs", "/api/v1/schedules")


def without_publishing_routes(fake, routes=ROUTES):
    """A PlantCraft older than API v1 results: the publishing routes answer 404."""

    handle = fake.handle
    calls = []

    def older(method, path, **kwargs):
        if method == "PUT" and path in routes:
            calls.append(path)
            return FakeResponse(404, {"detail": "Not Found"})
        return handle(method, path, **kwargs)

    fake.handle = older
    return calls


@pytest.fixture
def published(tmp_path):
    """A runtime and the fake's record of what Analytics published (``fake.links``)."""

    fake = make_fake()
    runtime = make_runtime(tmp_path, fake)
    yield runtime, fake
    runtime.shutdown()


def test_a_round_publishes_every_signal_and_the_asset(published):
    runtime, fake = published
    assert runtime.run_signal_quality("schedule")["status"] == "ok"
    assert {app for app, _subject, _kind in fake.links.results} == {"linkcraft"}
    assert {kind for _app, _subject, kind in fake.links.results} == {"signal_quality"}
    results = {subject: row for (_app, subject, _kind), row in fake.links.results.items()}
    suite = {"good": "ok", "suspect": "warning", "bad": "alarm"}
    for signal_id, (status, limiting) in EXPECTED.items():
        row = results[f"signal:{signal_id}"]
        assert row["status"] == suite[status]
        assert row["usable"] is (status != "bad")
        assert row["detail"]["limiting"] == limiting
        assert 0 <= row["score"] <= 100
        assert row["summary"]
        assert row["expires_at"] > row["at"]
    asset = results["asset:fic-110"]
    assert {item["role"] for item in asset["detail"]["signals"]} == {"pv", "sp", "op", "mode"}
    assert "asset:plant" not in results  # no signals of its own


def test_runs_and_schedule_are_reported(published):
    runtime, fake = published
    runtime.run_signal_quality("manual", started_by="engineer")
    (key, run), *others = fake.links.runs.items()
    assert not others and key == ("linkcraft", run["id"]) and run["id"] == "signal-quality-1"
    assert (run["status"], run["trigger"]) == ("done", "manual")
    assert run["url"] == "/link/runs/signal-quality-1"
    assert run["started_at"] and run["finished_at"]
    assert "signals" in run["summary"]
    rows = {row["id"]: row for row in fake.links.schedules["linkcraft"]}
    schedule = rows["round-signal_quality"]
    assert {key: schedule[key] for key in ("name", "cadence", "enabled", "url")} == {
        "name": "Signal quality",
        "cadence": "every 15 minutes",
        "enabled": True,
        "url": "/link/runs",
    }
    assert "round-cpm" in rows  # one list: the loops' round and Signal quality together
    # What each runs on, so an Alarms rule over an execution covers its assets.
    assert all(
        ref.startswith(("asset:", "signal:")) for row in rows.values() for ref in row["subjects"]
    )


def test_a_run_is_running_while_the_round_runs(published):
    runtime, fake = published
    seen = []
    keep = runtime.quality_engine.check

    def check(*args, **kwargs):
        seen.extend(run["status"] for run in fake.links.runs.values())
        return keep(*args, **kwargs)

    runtime.quality_engine.check = check
    runtime.run_signal_quality()
    assert seen == ["running"]


def test_checking_one_signal_publishes_it_and_its_assets(published):
    runtime, fake = published
    runtime.quality_engine.sync(runtime.signal_reader)
    with client_for(runtime, fake) as client:
        assert client.post("/link/api/signals/historian:FIC-110.PV/check").status_code == 200
    subjects = {subject for _app, subject, _kind in fake.links.results}
    assert subjects == {"signal:historian:FIC-110.PV", "asset:fic-110"}


def test_an_older_processcraft_is_logged_once_and_the_round_still_works(tmp_path, caplog):
    fake = make_fake()
    calls = without_publishing_routes(fake)
    runtime = make_runtime(tmp_path, fake)
    try:
        with caplog.at_level(logging.WARNING, logger="linkcraft.data.suite"):
            assert runtime.run_signal_quality()["status"] == "ok"
            assert runtime.run_signal_quality()["status"] == "ok"
        notes = [record.getMessage() for record in caplog.records]
        assert sum("serve results" in note for note in notes) == 1
        assert sum("serve runs" in note for note in notes) == 1
        assert calls.count("/api/v1/results") == 1  # not asked again within the hour
        assert not fake.links.results
        assert runtime.quality_results.latest("historian:TI-101.PV")["status"] == "suspect"
    finally:
        runtime.shutdown()


def test_without_an_app_key_nothing_is_published(tmp_path):
    fake = make_fake()
    runtime = make_runtime(tmp_path, fake, app_key=False)
    try:
        runtime.publish_schedules()
        assert not fake.links.schedules and not fake.links.runs
    finally:
        runtime.shutdown()


def _verdict(signal, status, quality, apt=True, message="", checks=()):
    return {
        "signal": signal,
        "status": status,
        "quality": quality,
        "apt": apt,
        "message": message,
        "checks": list(checks),
        "checked_at": "2026-10-19T10:00:00+00:00",
    }


def test_the_asset_is_the_worst_of_its_signals():
    asset = {"id": "u1-fic", "signals": {"pv": "A", "op": "B", "sp": "C", "mode": None}}
    latest = {
        "A": _verdict("A", "good", 100.0),
        "B": _verdict("B", "bad", 10.0, apt=False, message="Gaps."),
        "C": _verdict("C", "suspect", 60.0),
    }
    row = asset_result(asset, latest, "2026-10-19T12:00:00+00:00")
    assert row["subject"] == "asset:u1-fic"
    assert (row["status"], row["score"], row["usable"]) == ("alarm", 10.0, False)
    assert row["summary"] == "OP (B): Gaps."
    latest["B"] = _verdict("B", "unknown", None, apt=False)
    row = asset_result(asset, latest, "")
    assert (row["status"], row["usable"]) == ("warning", None)
    assert asset_result({"id": "x", "signals": {"pv": "nope"}}, latest, "") is None


def test_a_signal_result_lists_only_the_checks_that_flagged_it():
    verdict = _verdict(
        "pi:FIC1001.PV",
        "suspect",
        70.0,
        message="Frozen.",
        checks=[
            {"check": "sq_frozen", "status": "warning", "score": 30.0, "message": "Frozen."},
            {"check": "sq_spikes", "status": "ok", "score": 0.0, "message": ""},
        ],
    )
    row = signal_result(verdict, "later")
    assert row["subject"] == "signal:pi:FIC1001.PV"
    assert [issue["check"] for issue in row["detail"]["issues"]] == ["sq_frozen"]
    assert signal_result({**verdict, "status": "unknown"}, "")["usable"] is None


def test_references():
    # A signal's reference is signal: plus its API v1 id, which Analytics never builds.
    assert signal_ref("pi:FIC1001.PV") == "signal:pi:FIC1001.PV"
    assert parse_ref("signal:pi:FIC1001.PV").signal_id == "pi:FIC1001.PV"
    assert parse_ref(signal_ref("historian:AREA 1/TI-1:A")).signal_id == "historian:AREA 1/TI-1:A"
    with pytest.raises(ValueError):
        parse_ref("tag:FIC1001")


def test_quality_points_for_histcraft_skip_unknown_verdicts():
    verdicts = [
        {**_verdict("pi:TI-1.PV", "good", 98.5), "window_end": "2026-10-19T12:00:00+00:00"},
        _verdict("pi:TI-2.PV", "unknown", None),
    ]
    (point,) = quality_points(verdicts)
    assert point["signal"] == "app-linkcraft:pi:TI-1.PV.quality"
    assert (point["subject"], point["result"]) == ("signal:pi:TI-1.PV", "signal_quality")
    assert (point["t"], point["v"]) == (["2026-10-19T12:00:00+00:00"], [98.5])
    assert (point["unit"], point["kind"]) == ("/100", "number")


def test_quality_series_are_written_as_derived_signals_and_never_checked(published):
    runtime, fake = published
    assert runtime.run_signal_quality()["status"] == "ok"
    series_id = "app-linkcraft:historian:TI-101.PV.quality"
    assert series_id in fake.derived
    (row,) = runtime.service_client.signals(app="linkcraft", subject="signal:historian:TI-101.PV")
    assert (row["id"], row["result"], row["unit"]) == (series_id, "signal_quality", "/100")
    published = runtime.quality_publisher.published["series"]
    assert published["sent"] == published["points"] > 0
    # The next round checks the plant's signals only, not the scores it wrote.
    assert runtime.run_signal_quality()["status"] == "ok"
    assert runtime.quality_results.latest(series_id) is None
    assert len(fake.derived[series_id]) == 1  # same window end: rewritten, never duplicated


def test_a_processcraft_without_the_series_route_still_gets_results(tmp_path):
    fake = make_fake()
    calls = without_publishing_routes(fake, ("/api/v1/series",))
    runtime = make_runtime(tmp_path, fake)
    try:
        assert runtime.run_signal_quality()["status"] == "ok"
        assert runtime.run_signal_quality()["status"] == "ok"
        assert calls.count("/api/v1/series") == 1
        assert runtime.quality_publisher.published["series"]["sent"] == 0
        assert fake.links.results
    finally:
        runtime.shutdown()


def test_a_signal_quality_round_with_nothing_to_check_leaves_no_run(tmp_path, fake):
    rt = make_runtime(tmp_path, fake, app_key=False)
    try:
        assert rt.run_signal_quality()["signals"] == 0
        assert rt.quality_results.rounds(5) == []
    finally:
        rt.shutdown()
