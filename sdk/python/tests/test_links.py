"""Results, events, runs and schedules: the client against FakePlantCraft."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plantcraft_sdk.client import BadRequest, Forbidden, NotFound
from plantcraft_sdk.contract import ContractError
from plantcraft_sdk.links import (
    MAX_EVENTS,
    LinkError,
    check_url,
    event_kind,
    parse_events,
    result_kind,
    subjects_param,
)
from plantcraft_sdk.testing import DEFAULT_ASSETS, FakePlantCraft

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def fake():
    return FakePlantCraft(now=NOW)


def _service(fake):
    return fake.client(None, app="linkcraft", key="test-app-key")


def test_results_are_replaced_per_subject_and_kind_and_expire(fake):
    client = _service(fake)
    receipt = client.put_results(
        [
            {
                "subject": "asset:fic-101",
                "kind": "loop_health",
                "status": "warning",
                "score": 60,
                "usable": True,
                "value": 12.5,
                "summary": "Oscillating",
                "detail": {"period_s": 120},
                "at": "2026-10-19T11:00:00Z",
                "expires_at": "2026-10-19T13:00:00Z",
            },
            {"subject": "asset:nope", "kind": "loop_health", "status": "ok"},
            {"subject": "signal:fake:FIC-101.PV", "kind": "linkcraft.loop_health", "status": "ok"},
        ]
    )
    assert receipt["saved"] == 2
    assert [(error["index"], error["status"]) for error in receipt["errors"]] == [(1, 404)]
    [result] = client.results(["asset:fic-101"])
    assert result["app"] == "linkcraft" and result["kind"] == "loop_health"
    assert result["status"] == "warning" and result["stale"] is False
    assert result["at"] == "2026-10-19T11:00:00.000Z" and result["detail"] == {"period_s": 120}
    both = client.results(["asset:fic-101", "signal:fake:FIC-101.PV"], kind="linkcraft.loop_health")
    assert len(both) == 2
    assert client.results(["asset:fic-101"], app="histcraft") == []
    client.put_results([{"subject": "asset:fic-101", "kind": "loop_health", "status": "ok"}])
    assert [item["status"] for item in client.results("asset:fic-101")] == ["ok"]
    history = client.result_history("asset:fic-101", kind="loop_health")
    assert [item["status"] for item in history] == ["warning", "ok"]
    # After expires_at a result reads as unknown and stale.
    client.put_results(
        [
            {
                "subject": "asset:lic-102",
                "kind": "loop_health",
                "status": "ok",
                "expires_at": "2026-10-19T11:59:00Z",
            }
        ]
    )
    [stale] = client.results("asset:lic-102")
    assert stale["status"] == "unknown" and stale["stale"] is True


@pytest.mark.parametrize(
    "item",
    [
        {"status": "great"},
        {"score": 101},
        {"score": -1},
        {"score": True},
        {"usable": "yes"},
        {"value": "12"},
        {"summary": "x" * 301},
        {"detail": {"blob": "x" * 17_000}},
        {"detail": [1, 2]},
        {"at": "yesterday"},
        {"expires_at": "2026-13-01"},
    ],
)
def test_results_outside_the_contract_are_422(fake, item):
    body = {"subject": "asset:fic-101", "kind": "loop_health", "status": "ok", **item}
    with pytest.raises(BadRequest) as error:
        _service(fake).put_results([body])
    assert error.value.status_code == 422


def test_non_finite_values_are_refused(fake):
    answer = fake.handle(
        "PUT",
        "/api/v1/results",
        headers={"authorization": f"Bearer {fake.token('engineer')}"},
        body=b'[{"subject": "asset:fic-101", "kind": "k", "status": "ok", "value": NaN,'
        b' "app": "linkcraft"}]',
    )
    assert answer.status == 422


def test_a_person_writes_only_for_apps_they_edit(fake):
    engineer = fake.client("engineer")  # client.app unknown: items must name the app
    item = {"subject": "asset:fic-101", "kind": "loop_health", "status": "ok"}
    receipt = engineer.put_results([item])
    assert receipt["errors"][0]["status"] == 422
    assert engineer.put_results([{**item, "app": "linkcraft"}])["saved"] == 1
    operator = fake.client("operator")
    assert operator.put_results([{**item, "app": "linkcraft"}])["errors"][0]["status"] == 403
    service = _service(fake)
    assert service.put_results([{**item, "app": "histcraft"}])["errors"][0]["status"] == 403


def test_events_kinds_refs_and_paging(fake):
    client = _service(fake)
    first = client.post_event(
        "linkcraft.finding.opened",
        "asset:fic-101",
        summary="Valve sticks",
        refs=["signal:fake:FIC-101.OP", "run:linkcraft/r1"],
        payload={"index": 0.8},
    )
    assert first["kind"] == "linkcraft.finding.opened" and first["app"] == "linkcraft"
    assert first["refs"] == ["asset:fic-101", "signal:fake:FIC-101.OP", "run:linkcraft/r1"]
    second = client.post_event("linkcraft.finding.closed", "asset:fic-101")
    assert [item["id"] for item in client.events(ref="asset:fic-101")] == [1, 2]
    assert client.events(ref="run:linkcraft/r1") == [first]
    assert client.events(after=first["id"]) == [second]
    assert client.events(kind="linkcraft.finding.closed") == [second]
    with pytest.raises(BadRequest):
        client.post_event("histcraft.quality.changed", "asset:fic-101")
    with pytest.raises(BadRequest):
        client.post_event("linkcraft.finding.opened", "asset:fic-101", refs=["loop:x"])
    with pytest.raises(NotFound):
        client.post_event("linkcraft.finding.opened", "asset:nope")
    with pytest.raises(BadRequest):
        client.events(limit=501)


def test_many_events_go_in_lists_of_up_to_1000(fake):
    client = _service(fake)
    events = [
        {"kind": "linkcraft.finding.opened", "subject": "asset:fic-101", "summary": f"#{index}"}
        for index in range(2 * MAX_EVENTS + 5)
    ]
    events[3]["subject"] = "asset:nope"
    events[MAX_EVENTS + 1]["kind"] = "histcraft.quality.changed"
    client.token()
    before = fake.requests
    receipt = client.post_events(events)
    assert fake.requests - before == 3
    assert receipt["saved"] == len(events) - 2 and len(receipt["ids"]) == len(events)
    assert [(e["index"], e["id"], e["status"]) for e in receipt["errors"]] == [
        (3, "asset:nope", 404),
        (MAX_EVENTS + 1, "asset:fic-101", 422),
    ]
    assert receipt["ids"][3] is None and receipt["ids"][MAX_EVENTS + 1] is None
    stored = {event["id"]: event["summary"] for event in fake.links.events}
    assert stored[receipt["ids"][-1]] == f"#{len(events) - 1}"
    assert client.post_events([]) == {"saved": 0, "ids": [], "errors": [], "repeated": 0}
    with pytest.raises(BadRequest):
        client.post_events([{"kind": "linkcraft.finding.opened", "subject": "x", "refs": ["y"]}])
    # The single form still answers the event.
    one = fake.http_client().post(
        "/api/v1/events",
        json={"kind": "linkcraft.note.added", "subject": "asset:fic-101"},
        headers={"Authorization": f"Bearer {client.token()}"},
    )
    assert one.status_code == 201 and one.json()["kind"] == "linkcraft.note.added"


def test_parse_events_takes_one_object_or_a_list():
    item = {"kind": "linkcraft.finding.opened", "subject": "asset:a"}
    assert parse_events(item)[1] is False and parse_events([item, item])[1] is True
    for body in ([], [item] * (MAX_EVENTS + 1), "x", None, [item, 1]):
        with pytest.raises(ContractError):
            parse_events(body)


def test_a_subject_with_a_comma_is_one_subject():
    """Ids may hold commas and spaces: subjects go as repeated parameters, never split."""

    assets = [*DEFAULT_ASSETS, {"id": "Unit 2,FIC 101", "name": "x", "kind": "loop"}]
    assets.append({"id": "Unit 2", "name": "y", "kind": "unit"})
    fake = FakePlantCraft(now=NOW, assets=assets)
    client = _service(fake)
    subject, decoy = "asset:Unit 2,FIC 101", "asset:Unit 2"
    client.put_results(
        [
            {"subject": subject, "kind": "loop_health", "status": "alarm"},
            {"subject": decoy, "kind": "loop_health", "status": "ok"},
        ]
    )
    assert [item["subject"] for item in client.results(subject)] == [subject]
    assert [item["subject"] for item in client.results([subject, "asset:fic-101"])] == [subject]
    assert len(client.results([subject, decoy])) == 2
    for transport in ("mock", "asgi"):
        http = fake.http_client(transport=transport)
        answer = http.get(
            "/api/v1/results",
            params={"subject": [subject, "asset:fic-101"]},
            headers={"Authorization": f"Bearer {client.token()}"},
        )
        assert [item["subject"] for item in answer.json()] == [subject], transport
    assert subjects_param([" a,b ", "a,b", "c"]) == ["a,b", "c"]


def test_runs_and_schedules(fake):
    client = _service(fake)
    receipt = client.put_runs(
        [
            {
                "id": "r1",
                "name": "Morning round",
                "status": "running",
                "trigger": "schedule",
                "started_at": "2026-10-19T06:00:00-03:00",
                "subjects": ["asset:fic-101", "asset:lic-102"],
                "url": "/link/runs/r1",
            },
            {"id": "r2", "status": "done", "trigger": "manual", "url": "javascript:alert(1)"},
            {"id": "r3", "status": "done", "trigger": "api", "subjects": ["asset:nope"]},
        ]
    )
    assert receipt["saved"] == 1
    assert [(e["id"], e["status"]) for e in receipt["errors"]] == [("r2", 422), ("r3", 404)]
    [run] = client.runs(subject="asset:lic-102")
    assert run["started_at"] == "2026-10-19T09:00:00.000Z" and run["app"] == "linkcraft"
    client.put_runs([{"id": "r1", "status": "done", "trigger": "schedule"}])
    assert client.runs(status="done")[0]["id"] == "r1" and client.runs(status="running") == []
    with pytest.raises(BadRequest):
        client.runs(status="sleeping")
    with pytest.raises(BadRequest):
        client.put_runs([{"id": "r4", "status": "done"}])  # trigger is required
    # For the suite's Queue (SDK 0.53.0): who started it, how far it went, how to cancel it.
    queued = {"id": "r5", "status": "running", "trigger": "manual", "by": "engineer"}
    queued |= {"progress": 0.25, "step": "Reading", "cancel": "/link/api/runs/r5/cancel"}
    assert client.put_runs([queued])["saved"] == 1
    [mine] = client.runs(by="engineer")
    assert (mine["progress"], mine["step"], mine["cancel"]) == (
        0.25,
        "Reading",
        "/link/api/runs/r5/cancel",
    )
    away = client.put_runs([{**queued, "cancel": "/alarm/api/x"}])
    assert away["saved"] == 0 and away["errors"][0]["status"] == 422
    schedules = [
        {"id": "daily", "name": "Daily round", "cadence": "every day at 06:00"},
        {"id": "weekly", "cadence": "every Monday", "enabled": False, "url": "https://x.test/"},
    ]
    assert client.put_schedules(schedules)["saved"] == 2
    assert [item["id"] for item in client.schedules(app="linkcraft")] == ["daily", "weekly"]
    assert client.put_schedules([])["saved"] == 0
    assert client.schedules() == []
    with pytest.raises(BadRequest):
        client.put_schedules([{"id": "a"}, {"id": "a"}])


def test_reads_are_for_viewers_and_up(fake):
    fake.users["wall"] = {"name": "Wall", "level": "dashboards", "apps": {}}
    wall = fake.client("wall")
    for read in (wall.results, wall.events, wall.runs, wall.schedules):
        with pytest.raises(Forbidden):
            read()
    assert fake.client("operator").runs() == []


def test_shared_rules():
    assert result_kind("linkcraft.loop_health", "linkcraft") == "loop_health"
    assert event_kind("linkcraft.finding.opened", "linkcraft") == "linkcraft.finding.opened"
    assert check_url("/link/runs/1", "/link/") == "/link/runs/1"
    assert check_url("https://elsewhere.test/r", "/link/") == "https://elsewhere.test/r"
    for url in ("/dash/x", "//evil.test/x", "/link/../admin", "ftp://x.test", "/link/a b"):
        with pytest.raises(LinkError):
            check_url(url, "/link/")
    with pytest.raises(LinkError):
        event_kind("linkcraft.Finding", "linkcraft")
