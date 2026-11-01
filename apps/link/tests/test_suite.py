"""How Analytics links to the suite through PlantCraft (app standard, sections 2 and 6).

Results on assets, health and status as derived series, finding events, rounds as runs, the
schedule list, and the Signal quality protocol's verdicts read before a loop is judged; every
endpoint optional (a 404 is logged once). The SDK's
``FakePlantCraft`` serves the suite endpoints with PlantCraft's rules and keeps what
Analytics published in ``fake.links``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from plantcraft_sdk.client import NotFound
from plantcraft_sdk.refs import parse_ref, signal_ref
from plantcraft_sdk.testing import FakeResponse

from linkcraft.data.suite import MAX_SUMMARY, SuiteClient, summary_text
from linkcraft.loops.suite import (
    FINDING_OPENED,
    FindingStore,
    cadence_words,
    condition_key,
    quality_verdicts,
    suite_status,
)
from tests.conftest import client_for, make_runtime
from tests.plant import make_fake, sid


@pytest.fixture
def suite_fake():
    return make_fake(catalog=True)


@pytest.fixture
def rt(tmp_path, suite_fake):
    runtime = make_runtime(tmp_path, suite_fake)
    yield runtime
    runtime.shutdown()


def _verdict(signal_id: str, *, status="good", message="Good data.", age_minutes=0.0):
    """One verdict of the Signal quality protocol, as ``signals.store`` keeps it."""

    checked = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return {
        "signal": signal_id,
        "checked_at": checked.isoformat(),
        "status": status,
        "quality": {"good": 95.0, "suspect": 60.0, "bad": 10.0}.get(status),
        "apt": status != "bad",
        "limiting": None,
        "message": message,
        "checks": [],
    }


def test_references_keep_ids_whole():
    """What Analytics relies on in ``plantcraft_sdk.refs``: an API v1 id goes in and out whole."""

    for signal_id in ("pi:FIC1001.PV", "pi:Unit 2\\FIC 101:PV/x", "fake:FIC-101.PV"):
        ref = signal_ref(signal_id)
        assert ref == f"signal:{signal_id}" and parse_ref(ref).signal_id == signal_id
    assert parse_ref("asset:u200/fic:1").id == "u200/fic:1"


def test_summaries_fit_what_processcraft_keeps():
    assert summary_text("a  b\nc") == "a b c"
    long = summary_text("x" * 1000)
    assert len(long) == MAX_SUMMARY and long.endswith("…")


def test_each_round_publishes_loop_health_on_the_asset(rt, suite_fake):
    rt.run_round()
    rows = {subject: row for (app, subject, kind), row in suite_fake.links.results.items()}
    assert {app for app, _, _ in suite_fake.links.results} == {"linkcraft"}
    assert {kind for _, _, kind in suite_fake.links.results} == {"loop_health"}
    healthy = rows["asset:fic-101"]
    latest = rt.latest.summaries("cpm", "loop")
    summary = latest["fic-101"]["summary"]
    assert healthy["score"] == summary["health"] and healthy["usable"] is None
    assert healthy["status"] == suite_status(summary) == "ok"
    assert healthy["detail"]["url"] == "/link/assets/fic-101"
    # Two round periods (10 minutes by default) after the round.
    lifetime = pd.Timestamp(healthy["expires_at"]) - pd.Timestamp(healthy["at"])
    assert lifetime == pd.Timedelta(minutes=20)
    saturated = rows["asset:pic-103"]
    assert saturated["status"] == "alarm"
    assert saturated["summary"] == latest["pic-103"]["summary"]["limiting"]["finding"]
    frozen = rows["asset:tic-104"]  # rejected by the gate: no health, so unknown
    assert frozen["status"] == "unknown" and frozen["score"] is None
    assert "asset:fic-106" not in rows  # an incomplete record is never judged


def test_loops_defined_here_publish_nothing(rt, suite_fake):
    from linkcraft.config import LoopConfig, LoopSignals

    rt.run_round()
    rt.loops.save_loop(
        LoopConfig(loop_id="mine", name="Mine", signals=LoopSignals(pv=sid("FIC-101.PV"))),
        origin="user",
    )
    rt.run_round()
    assert not [subject for _, subject, _ in suite_fake.links.results if "mine" in subject]


def _signal(fake, signal_id):
    return next((item for item in fake.signals if item["id"] == signal_id), None)


def _points(fake, signal_id):
    return {pd.Timestamp(at): value for at, value in fake.derived.get(signal_id, {}).items()}


def test_each_round_writes_health_as_a_derived_series(rt, suite_fake):
    writes = {"n": 0}
    original = suite_fake._route_put_series

    def counted(request):
        writes["n"] += 1
        return original(request)

    suite_fake._route_put_series = counted
    outcome = rt.run_round()
    at = pd.Timestamp(outcome["header"]["completed_at"])
    latest = rt.latest.summaries("cpm", "loop")
    assert writes["n"] == 1  # every loop's health and the algorithms' versions in one list
    # One series per asset, algorithm and output: <loop>.<algorithm>.health.
    health = _signal(suite_fake, "app-linkcraft:fic-101.flow_loop.health")
    assert health is not None
    assert {key: health[key] for key in ("name", "unit", "kind", "subject", "result", "app")} == {
        "name": "FIC-101 · Flow loop · Health",
        "unit": "/100",
        "kind": "number",
        "subject": "asset:fic-101",
        "result": "loop_health",
        "app": "linkcraft",
    }
    assert health["source"] == "app-linkcraft"
    assert _points(suite_fake, health["id"]) == {at: latest["fic-101"]["summary"]["health"]}
    # The status band is in the result, not in a second series (fewer signals in the source).
    assert _signal(suite_fake, "app-linkcraft:fic-101.flow_loop.status") is None
    # No health this round (the gate rejected the data): an empty point.
    assert _points(suite_fake, "app-linkcraft:tic-104.flow_loop.health") == {at: None}
    # The same loops as the results: an incomplete record is never judged.
    mine = [item for item in suite_fake.signals if item.get("app") == "linkcraft"]
    published = {item["subject"] for item in mine if item.get("subject")}
    results = {subject for (_, subject, _) in suite_fake.links.results}
    assert published == results and "asset:fic-106" not in published
    assert outcome["header"]["published"]["series"] == len(results)
    # Each algorithm's version: one text series per algorithm, a point when it changes.
    versions = {item["id"]: item["name"] for item in mine if item["id"].endswith(".version")}
    assert versions == {
        "app-linkcraft:algorithm.flow_loop.version": "Flow loop · Version",
        "app-linkcraft:algorithm.temperature_loop.version": "Temperature or pressure loop · Version",
    }
    assert set(_points(suite_fake, "app-linkcraft:algorithm.flow_loop.version").values()) == {"v1"}
    # The next round adds one point per loop; read back like any other signal.
    second = pd.Timestamp(rt.run_round()["header"]["completed_at"])
    assert set(_points(suite_fake, health["id"])) == {at, second}
    assert len(_points(suite_fake, "app-linkcraft:algorithm.flow_loop.version")) == 1
    frame = rt.service_client.series(
        health["id"], start=at - pd.Timedelta(minutes=1), end=second + pd.Timedelta(minutes=1)
    )
    assert len(frame["t"]) == len({at, second})


def test_loops_defined_here_write_no_series(rt, suite_fake):
    from linkcraft.config import LoopConfig, LoopSignals

    rt.loops.save_loop(
        LoopConfig(loop_id="mine", name="Mine", signals=LoopSignals(pv=sid("FIC-101.PV"))),
        origin="user",
    )
    rt.run_round()
    assert not [item for item in suite_fake.signals if item["id"].startswith("app-linkcraft:mine")]


def test_a_failed_series_write_does_not_fail_the_round(rt, suite_fake, caplog):
    suite_fake._route_put_series = lambda request: FakeResponse(503, {"detail": "busy"})
    with caplog.at_level(logging.WARNING, logger="linkcraft.data.suite"):
        outcome = rt.run_round()
    assert outcome["status"] == "ok" and outcome["header"]["published"]["series"] == 0
    assert suite_fake.links.results and suite_fake.links.events  # the rest went through
    assert not suite_fake.derived
    assert any("series failed" in record.getMessage() for record in caplog.records)
    del suite_fake._route_put_series  # back to the fake's own route
    assert rt.suite.available("series")  # not a missing route: tried again next round
    assert rt.run_round()["header"]["published"]["series"] > 0 and suite_fake.derived


def test_a_missing_series_route_is_logged_once_and_tried_an_hour_later():
    class Client:
        calls = 0

        def put_series(self, *args, **kwargs):
            Client.calls += 1
            raise NotFound("PlantCraft answered 404: Not Found", status_code=404)

    now = {"t": 0.0}
    suite = SuiteClient(Client(), clock=lambda: now["t"])
    item = {"signal": "app-linkcraft:fic-101.health", "t": ["2026-10-20T00:00:00Z"], "v": [80.0]}
    assert suite.put_series([item]) == 0 and not suite.available("series")
    assert suite.put_series([item]) == 0 and Client.calls == 1
    now["t"] = 3600.0
    suite.put_series([item])
    assert Client.calls == 2


def test_a_series_item_processcraft_cannot_hold_is_left_out(rt, suite_fake):
    from linkcraft.loops.suite import SuitePublisher

    publisher = SuitePublisher(rt.db, rt.suite)
    payloads = {
        "ok": {"config": {"name": "OK-1"}, "summary": {"health": 90.0, "status": "normal"}},
        "bad\x01": {"config": {"name": "Bad"}, "summary": {"health": 10.0, "status": "critical"}},
    }
    written = publisher._series(payloads, list(payloads), datetime.now(timezone.utc))
    assert written == 1
    assert (
        _signal(suite_fake, "app-linkcraft:ok.cpm.health")["name"] == "OK-1 · Loop methods · Health"
    )


def test_findings_open_once_and_close_when_the_method_stops_flagging(rt, suite_fake):
    rt.run_round()
    opened = [
        item for item in suite_fake.links.events if item["kind"] == "linkcraft.finding.opened"
    ]
    assert opened, "the known-fault loops open findings"
    assert all(item["subject"].startswith("asset:") for item in opened)
    assert all(item["refs"][0] == item["subject"] for item in opened)
    assert any(ref.startswith("run:linkcraft/round-") for ref in opened[0]["refs"])
    saturation = [
        item
        for item in opened
        if item["subject"] == "asset:pic-103"
        and item["payload"]["method_id"] == "op_saturation_fraction"
    ]
    assert len(saturation) == 1 and saturation[0]["summary"]
    count = len(suite_fake.links.events)
    rt.run_round()
    assert len(suite_fake.links.events) == count  # same findings: nothing new
    # A finding open in PlantCraft that the methods no longer raise is closed.
    store = FindingStore(rt.db)
    store.opened("fic-101", "pv_variability", "warning", "Old finding.", "2026-10-01T00:00:00Z")
    # PlantCraft keeps only changes: the end it accepts is of a condition it saw open.
    suite_fake.links.events.append(
        {"app": "linkcraft", "kind": FINDING_OPENED, "subject": "asset:fic-101", "phase": "start",
         "key": condition_key("fic-101", "pv_variability"), "severity": "warning"}
    )  # fmt: skip
    rt.run_round()
    closed = [
        item for item in suite_fake.links.events if item["kind"] == "linkcraft.finding.closed"
    ]
    assert [(item["subject"], item["payload"]["method_id"]) for item in closed] == [
        ("asset:fic-101", "pv_variability")
    ]
    assert "fic-101" not in store.open_findings() or (
        "pv_variability" not in store.open_findings()["fic-101"]
    )


def test_a_rejected_event_is_sent_again_next_round(rt, suite_fake, monkeypatch):
    calls = {"n": 0}
    original = suite_fake._route_post_event

    def refuse_first(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(503, {"detail": "busy"})
        return original(request)

    monkeypatch.setattr(suite_fake, "_route_post_event", refuse_first)
    rt.run_round()
    assert not suite_fake.links.events  # the list failed: nothing is recorded
    assert FindingStore(rt.db).open_findings() == {}
    rt.run_round()
    assert suite_fake.links.events


def test_rounds_are_runs_with_their_trigger(rt, suite_fake):
    rt.run_round("schedule")
    (run,) = suite_fake.links.runs.values()
    assert run["status"] == "done" and run["trigger"] == "schedule"
    assert run["finished_at"] and run["url"] == "/link/runs"
    assert "asset:fic-101" in run["subjects"] and "loops analysed" in run["summary"]


def test_a_round_started_by_a_person_is_a_manual_run(rt, suite_fake):
    rt.run_round("schedule")  # the start-up round
    with client_for(rt, suite_fake) as client:
        answer = client.post("/link/api/round").json()
        assert answer["started"] is True
        assert rt.wait_for([answer["job_id"]], 10)
    triggers = sorted(row["trigger"] for row in suite_fake.links.runs.values())
    assert triggers == ["manual", "schedule"]


def test_the_schedule_list_is_replaced_after_changes(rt, suite_fake):
    rt.run_round()
    (rows,) = suite_fake.links.schedules.values()
    assert [row["id"] for row in rows] == ["round-cpm", "round-signal_quality"]
    assert rows[0]["cadence"] == "every 10 minutes" and rows[0]["enabled"] is True
    with client_for(rt, suite_fake) as client:
        answer = client.post(
            "/link/api/schedules",
            json={
                "name": "Morning check",
                "loop_id": "fic-101",
                "cadence": "daily",
                "time_local": "06:00",
            },
        )
        assert answer.status_code == 201, answer.text
    rows = suite_fake.links.schedules["linkcraft"]
    assert {row["name"]: row["cadence"] for row in rows}["Morning check"] == "every day at 06:00"
    # What each runs on, so an Alarms rule over an execution covers its assets.
    subjects = {row["name"]: row["subjects"] for row in rows}
    assert subjects["Morning check"] == ["asset:fic-101"]


def test_cadence_words():
    assert cadence_words({"cadence": "weekly", "weekday": 2, "time_local": "07:30"}) == (
        "every Wednesday at 07:30"
    )
    assert cadence_words({"cadence": "hourly", "time_local": "00:15"}) == (
        "every hour at minute 15"
    )
    assert cadence_words({"cadence": "weekly", "weekday": 99}).startswith("every Monday")


def test_unusable_signal_quality_stops_the_loop_with_its_message(rt):
    bad = _verdict(sid("LIC-102.PV"), status="bad", message="Frozen for 3 h.")
    rt.quality_results.save([bad])
    rt.run_round()
    summary = rt.latest.summaries("cpm", "loop")["lic-102"]["summary"]
    assert summary["status"] == "no_data" and summary["health"] is None
    assert summary["data_quality"]["source"] == "signal_quality"
    assert summary["data_quality"]["reasons"] == [
        "Signal quality, fake:LIC-102.PV: Frozen for 3 h."
    ]
    assert "Frozen for 3 h." in summary["operating_state_reason"]


def test_good_signal_quality_on_every_signal_replaces_the_built_in_gate(rt):
    # TIC-104's PV is frozen: the built-in gate rejects it ...
    rt.run_round()
    assert rt.latest.summaries("cpm", "loop")["tic-104"]["summary"]["status"] == "no_data"
    # ... but when Signal quality vouches for every one of its signals, it decides.
    loop = rt.loops.get_loop("tic-104")
    from linkcraft.data.frames import loop_signal_ids

    rt.quality_results.save([_verdict(signal) for signal in loop_signal_ids(loop)])
    rt.run_round()
    summary = rt.latest.summaries("cpm", "loop")["tic-104"]["summary"]
    assert summary["data_quality"] == {
        "apt": True,
        "reasons": [],
        "checked": True,
        "source": "signal_quality",
    }
    results = rt.latest.results("cpm", "loop")["tic-104"]
    assert not [item for item in results if item["method_id"].startswith("dq_")]


def test_stale_or_partial_signal_quality_leaves_it_to_the_built_in_gate(rt):
    rt.run_round()
    loop = rt.loops.get_loop("tic-104")
    from linkcraft.data.frames import loop_signal_ids

    signals = loop_signal_ids(loop)
    rt.quality_results.save([_verdict(signal, age_minutes=600) for signal in signals])
    rt.run_round()
    summary = rt.latest.summaries("cpm", "loop")["tic-104"]["summary"]
    assert summary["data_quality"]["source"] == "gate" and summary["status"] == "no_data"
    rt.quality_results.save([_verdict(signals[0])])  # fresh, but only the PV
    rt.run_round()
    summary = rt.latest.summaries("cpm", "loop")["tic-104"]["summary"]
    assert summary["data_quality"]["source"] == "gate" and summary["status"] == "no_data"


def test_unknown_verdicts_say_nothing(rt):
    rt.sync_loops()
    loop = rt.loops.get_loop("lic-102")
    unknown = _verdict(sid("LIC-102.PV"), status="unknown")
    assert quality_verdicts({unknown["signal"]: unknown}, [loop], max_age_minutes=60) == {}


def test_without_the_suite_endpoints_a_round_still_works_and_logs_once(tmp_path, caplog):
    fake = make_fake(older=True)
    runtime = make_runtime(tmp_path, fake)
    try:
        with caplog.at_level(logging.WARNING, logger="linkcraft.data.suite"):
            assert runtime.run_round()["status"] == "ok"
            first = fake.requests
            assert runtime.run_round()["status"] == "ok"
            second = fake.requests - first
        messages = [
            record.getMessage()
            for record in caplog.records
            if record.name == "linkcraft.data.suite"
        ]
        # runs, results, events, schedules, series
        assert len(messages) == len(set(messages)) == 5
        assert second < first  # the endpoints are left alone after their 404
    finally:
        runtime.shutdown()


def test_a_missing_endpoint_is_tried_again_an_hour_later():
    class Client:
        calls = 0

        def put_runs(self, *args, **kwargs):
            Client.calls += 1
            raise NotFound("PlantCraft answered 404: Not Found", status_code=404)

    now = {"t": 0.0}
    suite = SuiteClient(Client(), clock=lambda: now["t"])
    assert suite.put_runs([{"id": "r"}]) is False
    assert suite.put_runs([{"id": "r"}]) is False and Client.calls == 1
    now["t"] = 3600.0
    suite.put_runs([{"id": "r"}])
    assert Client.calls == 2


def test_a_refused_item_is_not_a_missing_endpoint():
    """A 404 naming what PlantCraft did not find leaves the endpoint in use."""

    class Client:
        calls = 0

        def post_events(self, *args, **kwargs):
            Client.calls += 1
            raise NotFound("x", status_code=404, detail="Asset not found. (asset:gone)")

    suite = SuiteClient(Client())
    event = {"kind": "linkcraft.finding.opened", "subject": "asset:gone", "summary": "s"}
    assert suite.post_events([event]) == [False] and suite.available("events")
    assert suite.post_events([event]) == [False] and Client.calls == 2


def test_events_go_as_lists_and_each_one_counts_on_its_own(caplog):
    """One request per ``MAX_EVENTS``; an event refused in the list leaves the others taken."""

    class Client:
        lists: list[list[dict]] = []

        def post_events(self, items):
            Client.lists.append(list(items))
            ids = [None if item["subject"] == "asset:gone" else n for n, item in enumerate(items)]
            errors = [
                {"index": n, "id": "asset:gone", "status": 404, "detail": "Asset not found."}
                for n, value in enumerate(ids)
                if value is None
            ]
            return {"saved": len(items) - len(errors), "ids": ids, "errors": errors}

    from linkcraft.data.suite import MAX_EVENTS

    events = [
        {"kind": "linkcraft.finding.opened", "subject": f"asset:loop-{n}", "summary": "x" * 400}
        for n in range(MAX_EVENTS + 5)
    ]
    events[3]["subject"] = "asset:gone"
    with caplog.at_level(logging.WARNING, logger="linkcraft.data.suite"):
        taken = SuiteClient(Client()).post_events(events)
    assert [len(chunk) for chunk in Client.lists] == [MAX_EVENTS, 5]
    assert taken == [n != 3 for n in range(MAX_EVENTS + 5)]
    assert len(Client.lists[0][0]["summary"]) == MAX_SUMMARY
    assert "asset:gone" in caplog.text


def test_a_list_refused_as_a_whole_goes_one_event_at_a_time():
    """A PlantCraft before lists (422) still gets the events; a refused one stays out."""

    from plantcraft_sdk.client import BadRequest

    class Client:
        single: list[str] = []

        def post_events(self, items):
            raise BadRequest("x", status_code=422, detail="Body must be an object.")

        def post_event(self, kind, subject, **kwargs):
            if subject == "asset:gone":
                raise NotFound("x", status_code=404, detail="Asset not found. (asset:gone)")
            Client.single.append(subject)
            return {"id": len(Client.single)}

    events = [
        {"kind": "linkcraft.finding.opened", "subject": subject, "summary": "s"}
        for subject in ("asset:a", "asset:gone", "asset:b")
    ]
    assert SuiteClient(Client()).post_events(events) == [True, False, True]
    assert Client.single == ["asset:a", "asset:b"]


def test_a_round_sends_its_events_in_one_request(rt, suite_fake, monkeypatch):
    posts = []
    original = suite_fake._route_post_event

    def count(request):
        posts.append(request.json())
        return original(request)

    monkeypatch.setattr(suite_fake, "_route_post_event", count)
    rt.run_round()
    assert len(posts) == 1 and isinstance(posts[0], list)
    assert len(posts[0]) == len(suite_fake.links.events) > 1
    opened = FindingStore(rt.db).open_findings()
    assert sum(len(methods) for methods in opened.values()) == len(posts[0])


@pytest.mark.parametrize(
    "verdict",
    [
        None,
        "nope",
        {"status": "bad", "checked_at": "not a date"},
        {"status": ["bad"], "apt": "no", "checked_at": None},
        {"status": "bad", "checked_at": 12},
    ],
)
def test_hostile_verdicts_never_crash(rt, verdict):
    rt.sync_loops()
    loop = rt.loops.get_loop("lic-102")
    verdicts = quality_verdicts({sid("LIC-102.PV"): verdict}, [loop], max_age_minutes=60)
    assert not verdicts.get("lic-102", {}).get("blocked")


def test_signal_ids_are_opaque_end_to_end(tmp_path):
    """A tag with spaces, ``,``, ``/``, ``\\`` and ``:`` reads, publishes and matches as one id.

    D2: ids are kept whole from the catalog to the verdicts the loops read.
    """

    from tests.plant import (
        ASSET_TYPES,
        NOW,
        PlantFake,
        catalog_assets,
        catalog_series,
        catalog_signals,
    )

    def odd(signal_id: str) -> str:  # fake:LIC-102.PV -> pi:Unit 2,A\LIC-102:PV/x
        tag = signal_id.partition(":")[2]
        return f"pi:Unit 2,A\\{tag.replace('.', ':')}/x"

    assets = catalog_assets()
    for asset in assets:
        signals = asset.get("signals") or {}
        asset["signals"] = {role: odd(value) for role, value in signals.items()}
    fake = PlantFake(
        assets=assets,
        signals=[{**item, "id": odd(item["id"]), "source": "pi"} for item in catalog_signals()],
        series={odd(key): value for key, value in catalog_series().items()},
        asset_types=ASSET_TYPES,
        now=NOW,
    )
    pv = odd(sid("LIC-102.PV"))
    runtime = make_runtime(tmp_path, fake)
    runtime.quality_results.save([_verdict(pv, status="bad", message="Bad.")])
    try:
        assert runtime.run_round()["status"] == "ok"
        summaries = runtime.latest.summaries("cpm", "loop")
        assert summaries["fic-101"]["summary"]["health"] is not None
        assert summaries["lic-102"]["summary"]["data_quality"]["reasons"] == [
            f"Signal quality, {pv}: Bad."
        ]
        # One signal read on its own goes through the URL path, encoded whole.
        assert fake.client("engineer").signal(pv)["id"] == pv
    finally:
        runtime.shutdown()


def test_a_run_lists_at_most_the_subjects_api_v1_takes(rt, suite_fake):
    from linkcraft.loops.suite import MAX_RUN_SUBJECTS

    sent = []
    rt.suite.put_runs = lambda rows: sent.extend(rows) or True
    subjects = [f"asset:loop-{number}" for number in range(MAX_RUN_SUBJECTS + 20)]
    rt.monitor.publisher.publish_run({"id": "r", "subjects": subjects})
    assert sent[0]["subjects"] == subjects[:MAX_RUN_SUBJECTS]


def test_events_after_a_failure_wait_for_the_next_round(rt, suite_fake, monkeypatch):
    original = suite_fake._route_post_event
    calls = {"n": 0}

    def refuse_the_second(request):
        calls["n"] += 1
        if calls["n"] == 2:
            return FakeResponse(503, {"detail": "busy"})
        return original(request)

    monkeypatch.setattr("linkcraft.data.suite.MAX_EVENTS", 2)
    monkeypatch.setattr(suite_fake, "_route_post_event", refuse_the_second)
    rt.run_round()
    first = len(suite_fake.links.events)
    assert first == 2 and calls["n"] == 2  # one list taken, the refusal stops the round's events
    opened = FindingStore(rt.db).open_findings()
    assert sum(len(methods) for methods in opened.values()) == first
    rt.run_round()
    assert len(suite_fake.links.events) > first
    assert {item["kind"] for item in suite_fake.links.events} == {"linkcraft.finding.opened"}
