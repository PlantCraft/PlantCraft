"""API v1 results, events, runs and schedules (docs/api-v1.md, "Results, events, runs and
schedules"): shapes, who may write and read, per-item errors, limits and hostile input.

The fixture ``central`` is the one of ``test_api_v1.py`` (shared through ``conftest.py``): PlantCraft with sign-in on and the people
``eng`` (editor), ``op`` (viewer of PlantCraft Analytics), ``nobody`` (viewer, no apps) and ``wall``
(dashboards).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.testing import FakePlantCraft
from tests.contract.test_api_v1 import _app_key, _as, _auth, _rt, _token

RESULT_FIELDS = {
    "app", "subject", "kind", "status", "score", "usable", "value", "summary", "detail", "at",
    "expires_at", "updated_at", "stale",
}  # fmt: skip
CHANGE_FIELDS = {"app", "subject", "kind", "status", "score", "usable", "value", "summary", "at"}
EVENT_FIELDS = {
    "id",
    "at",
    "app",
    "kind",
    "subject",
    "actor",
    "summary",
    "refs",
    "payload",
    "severity",
    "key",
    "phase",
    "category",
}
RUN_FIELDS = {
    "app", "id", "name", "status", "trigger", "started_at", "finished_at", "subjects", "summary",
    "url", "by", "progress", "step", "cancel", "updated_at",
}  # fmt: skip
SCHEDULE_FIELDS = {
    "app", "id", "name", "cadence", "next_run", "enabled", "url", "subjects", "updated_at",
}  # fmt: skip
RECEIPT_FIELDS = {"saved", "errors"}
ERROR_FIELDS = {"index", "id", "status", "detail"}


def _service(client) -> dict[str, str]:
    key = _app_key(client)["key"]
    grant = client.post("/api/v1/auth/service-token", json={"app": "linkcraft", "key": key})
    return _auth(grant.json()["token"])


def _asset(client) -> str:
    return client.get("/api/v1/assets", headers=_as(client, "eng")).json()[0]["id"]


def _result(subject: str = "signal:scenario:pv", **fields) -> dict:
    return {"subject": subject, "kind": "loop_health", "status": "ok", **fields}


# Results ------------------------------------------------------------------------------


def test_results_round_trip_with_a_service_token(central):
    headers = _service(central)
    asset = f"asset:{_asset(central)}"
    body = [
        _result(
            asset,
            status="warning",
            score=62.5,
            usable=True,
            value=12.3,
            summary="Oscillating",
            detail={"period_s": 120},
            at="2026-10-20T06:00:00-03:00",
            expires_at="2999-01-01T00:00:00Z",
        ),
        _result("signal:scenario:pv", kind="linkcraft.signal_health", usable=None),
        _result("asset:no-such-asset"),
        _result("signal:no-such-signal"),
    ]
    response = central.put("/api/v1/results", json=body, headers=headers)
    assert response.status_code == 200
    receipt = response.json()
    assert set(receipt) == RECEIPT_FIELDS and receipt["saved"] == 2
    assert [set(item) for item in receipt["errors"]] == [ERROR_FIELDS, ERROR_FIELDS]
    assert [(e["index"], e["id"], e["status"]) for e in receipt["errors"]] == [
        (2, "asset:no-such-asset", 404),
        (3, "signal:no-such-signal", 404),
    ]
    reader = _as(central, "op")
    found = central.get(
        "/api/v1/results", params={"subject": [asset, "signal:scenario:pv"]}, headers=reader
    ).json()
    assert [set(item) for item in found] == [RESULT_FIELDS, RESULT_FIELDS]
    first = next(item for item in found if item["subject"] == asset)
    assert first == {
        **first,
        "app": "linkcraft",
        "kind": "loop_health",
        "status": "warning",
        "score": 62.5,
        "usable": True,
        "value": 12.3,
        "summary": "Oscillating",
        "detail": {"period_s": 120},
        "at": "2026-10-20T09:00:00.000Z",
        "expires_at": "2999-01-01T00:00:00.000Z",
        "stale": False,
    }
    second = next(item for item in found if item["subject"] == "signal:scenario:pv")
    assert second["kind"] == "signal_health" and second["usable"] is None
    # kind may carry the app id.
    repeated = central.get(
        f"/api/v1/results?subject={asset}&subject=signal:scenario:pv&kind=linkcraft.loop_health",
        headers=reader,
    ).json()
    assert [item["subject"] for item in repeated] == [asset]
    assert central.get("/api/v1/results?app=histcraft", headers=reader).json() == []
    assert central.get("/api/v1/results?kind=histcraft.loop_health", headers=reader).json() == []
    assert len(central.get("/api/v1/results", headers=reader).json()) == 2


def test_a_put_replaces_the_row_and_each_status_change_is_kept(central):
    headers = _service(central)
    for status in ("ok", "ok", "alarm", "ok"):
        central.put("/api/v1/results", json=[_result(status=status)], headers=headers)
    rows = central.get("/api/v1/results?subject=signal:scenario:pv", headers=headers).json()
    assert len(rows) == 1 and rows[0]["status"] == "ok"
    history = central.get(
        "/api/v1/results/history", params={"subject": "signal:scenario:pv"}, headers=headers
    ).json()
    assert [item["status"] for item in history] == ["ok", "alarm", "ok"]
    assert all(set(item) == CHANGE_FIELDS for item in history)
    later = central.put(
        "/api/v1/results",
        json=[_result(status="warning", at="2999-01-01T00:00:00Z")],
        headers=headers,
    )
    assert later.json()["saved"] == 1
    after = central.get(
        "/api/v1/results/history",
        params={
            "subject": "signal:scenario:pv",
            "after": "2998-01-01T00:00:00Z",
            "kind": "loop_health",
        },
        headers=headers,
    ).json()
    assert [item["status"] for item in after] == ["warning"]
    bad = central.get(
        "/api/v1/results/history",
        params={"subject": "signal:scenario:pv", "after": "soon"},
        headers=headers,
    )
    assert bad.status_code == 422
    assert central.get("/api/v1/results/history", headers=headers).status_code == 422


def test_expired_results_are_unknown_and_stale(central):
    headers = _service(central)
    central.put(
        "/api/v1/results",
        json=[_result(status="ok", score=99, expires_at="2020-01-01T00:00:00Z")],
        headers=headers,
    )
    [row] = central.get("/api/v1/results?subject=signal:scenario:pv", headers=headers).json()
    assert row["status"] == "unknown" and row["stale"] is True and row["score"] == 99


def test_results_under_an_asset_and_grouped_by_their_unit(central):
    """Asked "which unit has most loops with problems", per-loop results gave the wrong unit."""

    assets = _rt(central).workspace.assets
    assets.save("t-unit-a", name="Unit A", kind="unit")
    assets.save("t-unit-b", name="Unit B", kind="unit")
    assets.save("t-eq-a", name="Pump A", kind="equipment", parent_id="t-unit-a")
    assets.save("t-loop-a", name="Loop A", kind="loop", parent_id="t-eq-a")
    assets.save("t-loop-b", name="Loop B", kind="loop", parent_id="t-unit-b")
    headers = _service(central)
    body = [
        _result("asset:t-loop-a", kind="placed_health", status="alarm"),
        _result("asset:t-loop-b", kind="placed_health", status="ok"),
        _result("signal:scenario:pv", kind="placed_health", status="warning"),
    ]
    assert central.put("/api/v1/results", json=body, headers=headers).status_code == 200
    read = "/api/v1/results?app=linkcraft&kind=placed_health"

    [row] = central.get(f"{read}&under=t-unit-a", headers=headers).json()
    assert row["subject"] == "asset:t-loop-a" and "group" not in row

    rows = central.get(f"{read}&group=unit", headers=headers).json()
    assert {row["subject"]: row["group"] for row in rows} == {
        "asset:t-loop-a": {"id": "t-unit-a", "name": "Unit A"},
        "asset:t-loop-b": {"id": "t-unit-b", "name": "Unit B"},
        "signal:scenario:pv": None,
    }
    assert central.get(f"{read}&under=nowhere", headers=headers).status_code == 404
    assert central.get(f"{read}&group=planet", headers=headers).status_code == 422


def test_history_and_runs_are_kept_90_days(central):
    store = _rt(central).workspace.results
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(timespec="seconds")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
    row = {
        "app": "linkcraft", "subject": "signal:scenario:pv", "kind": "k", "status": "ok", "score": None,
        "usable": None, "value": None, "summary": "", "detail": {}, "at": old, "expires_at": None,
    }  # fmt: skip
    store.put_results([row], now=old, cutoff=old)
    run = {
        "app": "linkcraft", "id": "old", "name": "", "status": "done", "trigger": "api",
        "started_at": None, "finished_at": None, "subjects": [], "summary": "", "url": None,
    }  # fmt: skip
    store.put_runs([run], now=old, cutoff=old)
    assert store.history("signal:scenario:pv") and store.runs()
    store.put_results([{**row, "status": "alarm", "at": now}], now=now, cutoff=cutoff)
    store.put_runs([{**run, "id": "new"}], now=now, cutoff=cutoff)
    assert [item["status"] for item in store.history("signal:scenario:pv")] == ["alarm"]
    assert [item["id"] for item in store.runs()] == ["new"]


def test_people_write_only_for_apps_they_edit(central):
    item = _result()
    engineer = _as(central, "eng")
    missing = central.put("/api/v1/results", json=[item], headers=engineer).json()
    assert missing["saved"] == 0 and missing["errors"][0]["status"] == 422
    ok = central.put("/api/v1/results", json=[{**item, "app": "linkcraft"}], headers=engineer)
    assert ok.json() == {"saved": 1, "errors": []}
    other = central.put("/api/v1/results", json=[{**item, "app": "alarmcraft"}], headers=engineer)
    assert other.json()["errors"][0]["status"] == 403
    for viewer in ("op", "nobody", "wall"):
        answer = central.put(
            "/api/v1/results", json=[{**item, "app": "linkcraft"}], headers=_as(central, viewer)
        )
        assert answer.json()["errors"][0]["status"] == 403, viewer
    service = _service(central)
    foreign = central.put("/api/v1/results", json=[{**item, "app": "histcraft"}], headers=service)
    assert foreign.json()["errors"][0]["status"] == 403
    own = central.put("/api/v1/results", json=[{**item, "app": "LinkCraft"}], headers=service)
    assert own.json()["saved"] == 1


def test_dashboards_people_read_none_of_it_and_tokens_are_required(central):
    wall = _as(central, "wall")
    for path in ("/api/v1/results", "/api/v1/events", "/api/v1/runs", "/api/v1/schedules"):
        assert central.get(path, headers=wall).status_code == 403, path
        assert central.get(path).status_code == 401, path
    history = central.get("/api/v1/results/history?subject=signal:scenario:pv", headers=wall)
    assert history.status_code == 403
    for method, path, body in (
        ("PUT", "/api/v1/results", []),
        ("POST", "/api/v1/events", {}),
        ("PUT", "/api/v1/runs", []),
        ("PUT", "/api/v1/schedules", []),
    ):
        assert central.request(method, path, json=body).status_code == 401, path
    events = central.post(
        "/api/v1/events",
        json={"app": "linkcraft", "kind": "linkcraft.x.done", "subject": "signal:scenario:pv"},
        headers=wall,
    )
    assert events.status_code == 403


BAD_RESULTS = [
    {"status": "fine"},
    {"status": None},
    {"score": 100.5},
    {"score": -0.1},
    {"score": "90"},
    {"score": True},
    {"usable": "true"},
    {"usable": 1},
    {"value": "1.5"},
    {"value": [1]},
    {"summary": "x" * 301},
    {"detail": "text"},
    {"detail": {"x": "y" * (16 * 1024)}},
    {"at": "2026-02-30T00:00:00Z"},
    {"at": 1760000000},
    {"expires_at": "tomorrow"},
    {"subject": ""},
    {"kind": ""},
]


@pytest.mark.parametrize("fields", BAD_RESULTS, ids=[str(item)[:40] for item in BAD_RESULTS])
def test_results_outside_the_contract_are_422_for_the_whole_request(central, fields):
    headers = _as(central, "eng")
    body = [{**_result(app="linkcraft"), **fields}, _result(app="linkcraft", kind="other")]
    response = central.put("/api/v1/results", json=body, headers=headers)
    assert response.status_code == 422, response.text
    assert response.json()["detail"].startswith("[0] ")
    assert central.get("/api/v1/results", headers=headers).json() == []


@pytest.mark.parametrize(
    "raw",
    [
        b'[{"subject": "signal:scenario:pv", "kind": "k", "status": "ok", "app": "linkcraft", "value": NaN}]',
        b'[{"subject": "signal:scenario:pv", "kind": "k", "status": "ok", "app": "linkcraft",'
        b' "score": Infinity}]',
        b'[{"subject": "signal:scenario:pv", "kind": "k", "status": "ok", "app": "linkcraft",'
        b' "detail": {"x": -Infinity}}]',
        b"NaN",
        b'{"subject": "signal:scenario:pv"}',
        b"[1, 2, 3]",
        b"[[[[[]]]]]",
    ],
)
def test_non_finite_numbers_and_odd_bodies_are_422_never_500(central, raw):
    headers = {**_as(central, "eng"), "Content-Type": "application/json"}
    for path in ("/api/v1/results", "/api/v1/runs", "/api/v1/schedules?app=linkcraft"):
        response = central.put(path, content=raw, headers=headers)
        assert response.status_code == 422, (path, response.text)
        json.dumps(response.json(), allow_nan=False)


def test_more_than_500_items_is_422(central):
    headers = _as(central, "eng")
    body = [_result(app="linkcraft", kind=f"k{index}") for index in range(501)]
    assert central.put("/api/v1/results", json=body, headers=headers).status_code == 422
    assert central.put("/api/v1/results", json=body[:500], headers=headers).json()["saved"] == 500
    many = central.get(
        "/api/v1/results", params={"subject": [f"signal:s{i}" for i in range(501)]},
        headers=headers,
    )  # fmt: skip
    assert many.status_code == 422


def test_a_bare_signal_subject_is_stored_by_its_signal_id(central):
    """Deprecated until v1 is frozen: ``signal:<tag>`` of one source names that signal."""

    headers = _service(central)
    saved = central.put("/api/v1/results", json=[_result("signal:sp")], headers=headers).json()
    assert saved == {"saved": 1, "errors": []}
    reader = _as(central, "op")
    [row] = central.get("/api/v1/results?subject=signal:sp", headers=reader).json()
    assert row["subject"] == "signal:scenario:sp"
    named = central.get("/api/v1/results?subject=signal:scenario:sp", headers=reader).json()
    assert named == [row]
    history = central.get("/api/v1/results/history?subject=signal:sp", headers=reader).json()
    assert [item["subject"] for item in history] == ["signal:scenario:sp"]
    event = central.post(
        "/api/v1/events",
        json={"kind": "linkcraft.note.added", "subject": "signal:sp", "refs": ["signal:pv"]},
        headers=headers,
    ).json()
    assert event["subject"] == "signal:scenario:sp"
    assert event["refs"] == ["signal:scenario:sp", "signal:scenario:pv"]
    events = central.get("/api/v1/events", params={"ref": "signal:pv"}, headers=reader).json()
    assert [item["id"] for item in events] == [event["id"]]
    runs = central.put(
        "/api/v1/runs",
        json=[{"id": "r1", "status": "done", "trigger": "api", "subjects": ["signal:sp"]}],
        headers=headers,
    ).json()
    assert runs["saved"] == 1
    [run] = central.get("/api/v1/runs", params={"subject": "signal:sp"}, headers=reader).json()
    assert run["subjects"] == ["signal:scenario:sp"]


def test_stored_bare_signal_refs_are_renamed_once(central):
    """Rows written before D2 (``signal:<tag>``) gain their source the first time it runs."""

    from processcraft.platform.signals import RENAME_MIGRATION, rename_signal_refs

    rt = _rt(central)
    workspace = rt.workspace
    now = "2026-10-20T06:00:00+00:00"
    old = {
        "app": "linkcraft", "subject": "signal:pv", "kind": "k", "status": "ok", "score": None,
        "usable": None, "value": None, "summary": "", "detail": {}, "at": now, "expires_at": None,
    }  # fmt: skip
    workspace.results.put_results([old], now=now, cutoff="2000-01-01")
    workspace.results.put_runs(
        [{"app": "linkcraft", "id": "r0", "name": "", "status": "done", "trigger": "api",
          "started_at": None, "finished_at": None, "subjects": ["signal:pv", "signal:op"],
          "summary": "", "url": None}],
        now=now, cutoff="2000-01-01",
    )  # fmt: skip
    event = workspace.events.publish(
        "linkcraft.x.done", "signal:pv", source="linkcraft", refs=["signal:op", "user:eng"]
    )
    assert workspace.migrated(RENAME_MIGRATION)  # ran at start, on an empty database
    assert rename_signal_refs(rt.platform) is None  # and only once
    with workspace._connect() as connection:
        connection.execute("DELETE FROM workspace_migrations")
    counts = rename_signal_refs(rt.platform)
    assert counts == {
        "refs": 2, "results": 1, "result_history": 1, "runs": 1, "events": 1, "event_refs": 2,
    }  # fmt: skip
    assert [row["subject"] for row in workspace.results.results()] == ["signal:scenario:pv"]
    assert workspace.results.history("signal:scenario:pv")
    assert workspace.results.runs()[0]["subjects"] == ["signal:scenario:pv", "signal:scenario:op"]
    renamed = workspace.events.get(event["event_id"])
    assert renamed["subject"] == "signal:scenario:pv"
    assert renamed["refs"] == ["signal:scenario:pv", "signal:scenario:op", "user:eng"]
    assert rename_signal_refs(rt.platform) is None
    # Already named refs stay as they are when it runs again from scratch.
    with workspace._connect() as connection:
        connection.execute("DELETE FROM workspace_migrations")
    assert rename_signal_refs(rt.platform)["refs"] == 0


def test_a_subject_with_a_comma_and_a_space_is_one_subject(central):
    """G41: ids may hold commas (refs.check_id), so ``subject`` is never split on them."""

    rt = _rt(central)
    tag = "Unit 2,FIC 101.PV"
    bound = [{"signal_id": tag, "role": ""}, {"signal_id": "Unit 2", "role": ""}]
    rt.workspace.assets.bind_signals(rt.platform.root_asset_id, bound)
    subject, decoy = f"signal:scenario:{tag}", "signal:scenario:Unit 2"
    body = [_result(subject, status="alarm"), _result(decoy)]
    assert central.put("/api/v1/results", json=body, headers=_service(central)).json() == {
        "saved": 2,
        "errors": [],
    }
    reader = _as(central, "op")
    [row] = central.get("/api/v1/results", params={"subject": subject}, headers=reader).json()
    assert row["subject"] == subject and row["status"] == "alarm"
    both = central.get(
        "/api/v1/results", params={"subject": [subject, "signal:scenario:pv"]}, headers=reader
    ).json()
    assert [item["subject"] for item in both] == [subject]
    # Until the freeze, an old client's comma-joined list still reads when no subject has
    # the whole text.
    joined = central.get(
        "/api/v1/results", params={"subject": f"{decoy},signal:scenario:pv"}, headers=reader
    ).json()
    assert [item["subject"] for item in joined] == [decoy]
    history = central.get("/api/v1/results/history", params={"subject": subject}, headers=reader)
    assert [item["status"] for item in history.json()] == ["alarm"]
    event = central.post(
        "/api/v1/events",
        json={"kind": "linkcraft.finding.opened", "subject": subject, "refs": [decoy]},
        headers=_service(central),
    )
    assert event.status_code == 201 and event.json()["refs"] == [subject, decoy]
    for ref in (subject, decoy):
        found = central.get("/api/v1/events", params={"ref": ref}, headers=reader).json()
        assert [item["id"] for item in found] == [event.json()["id"]]
    # The client sends one parameter per subject.
    client = PlantCraftClient("http://testserver", token=_token(central, "op"), http_client=central)
    assert [item["subject"] for item in client.results([subject])] == [subject]
    assert [item["subject"] for item in client.results([subject, decoy])] == [decoy, subject]


def test_results_come_in_pages_and_none_is_left_out(central, monkeypatch):
    """A list cut at 5,000 without a word hid the plant's results behind 1,000 bench loops
    (2026-10-27): the results now come in pages, with ``X-Next-Cursor`` while more are left."""

    headers = _as(central, "eng")
    body = [_result(app="linkcraft", kind=f"k{index}") for index in range(7)]
    assert central.put("/api/v1/results", json=body, headers=headers).json()["saved"] == 7
    seen, cursor, pages = [], None, 0
    while True:
        params = {"app": "linkcraft", "limit": 3, **({"cursor": cursor} if cursor else {})}
        page = central.get("/api/v1/results", params=params, headers=headers)
        assert page.status_code == 200 and len(page.json()) <= 3
        seen += [item["kind"] for item in page.json()]
        pages += 1
        cursor = page.headers.get("X-Next-Cursor")
        if not cursor:
            break
    assert pages == 3 and sorted(seen) == [f"k{index}" for index in range(7)]
    for bad in ("nonsense", "W10"):
        answer = central.get("/api/v1/results", params={"cursor": bad}, headers=headers)
        assert answer.status_code == 422
    # The SDK walks the pages.
    monkeypatch.setattr("plantcraft_sdk.client.PAGE_SIZE", 2)
    client = PlantCraftClient(
        "http://testserver", token=_token(central, "eng"), http_client=central
    )
    assert len(client.results(app="linkcraft")) == 7


# Events -------------------------------------------------------------------------------


def test_events_are_published_and_read_by_reference(central):
    headers = _service(central)
    asset = f"asset:{_asset(central)}"
    body = {
        "kind": "linkcraft.finding.opened",
        "subject": asset,
        "summary": "Valve sticks",
        "refs": ["signal:scenario:pv", "run:linkcraft/2026-10-20-0600", "user:eng", asset],
        "payload": {"index": 0.8},
    }
    response = central.post("/api/v1/events", json=body, headers=headers)
    assert response.status_code == 201, response.text
    event = response.json()
    assert set(event) == EVENT_FIELDS
    assert event["app"] == "linkcraft" and event["actor"] == "app:linkcraft"
    assert event["refs"] == [
        asset,
        "signal:scenario:pv",
        "run:linkcraft/2026-10-20-0600",
        "user:eng",
    ]
    assert event["payload"] == {"index": 0.8} and event["summary"] == "Valve sticks"
    closed = central.post(
        "/api/v1/events",
        json={"kind": "linkcraft.finding.closed", "subject": "signal:scenario:pv"},
        headers=headers,
    ).json()
    reader = _as(central, "op")

    def read(**params):
        answer = central.get("/api/v1/events", params=params, headers=reader)
        assert answer.status_code == 200, answer.text
        return [item["id"] for item in answer.json()]

    assert read(ref="signal:scenario:pv") == [event["id"], closed["id"]]
    assert read(ref="run:linkcraft/2026-10-20-0600") == [event["id"]]
    assert read(kind="linkcraft.finding.closed") == [closed["id"]]
    assert read(after=event["id"]) == [closed["id"]]
    assert read(limit=1) == [closed["id"]]
    assert read(after=0, limit=1) == [event["id"]]
    # The asset page's timeline shows the apps' events too.
    timeline = _rt(central).workspace.events.timeline(asset)
    assert [item["kind"] for item in timeline] == ["linkcraft.finding.opened"]
    for params in ({"limit": 501}, {"limit": 0}, {"after": "yesterday"}, {"after": -1}):
        assert central.get("/api/v1/events", params=params, headers=reader).status_code == 422


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"kind": "histcraft.quality.changed"}, 422),
        ({"kind": "finding.opened"}, 422),
        ({"kind": "linkcraft.Finding.Opened"}, 422),
        ({"kind": "linkcraft."}, 422),
        ({"subject": "asset:no-such-asset"}, 404),
        ({"subject": "loop:FIC-101"}, 422),
        ({"refs": ["loop:FIC-101"]}, 422),
        ({"refs": ["run:linkcraft"]}, 422),
        ({"refs": ["signal:scenario:pv"] * 51}, 422),
        ({"summary": "x" * 301}, 422),
        ({"payload": {"x": "y" * (16 * 1024)}}, 422),
        ({"payload": [1]}, 422),
        ({"app": "histcraft"}, 403),
    ],
)
def test_events_outside_the_contract(central, fields, status):
    body = {"kind": "linkcraft.finding.opened", "subject": "signal:scenario:pv", **fields}
    response = central.post("/api/v1/events", json=body, headers=_service(central))
    assert response.status_code == status, response.text


def test_a_list_of_events_is_one_request(central):
    """G39: up to 1,000 events per POST; failing items in ``errors``, the rest saved."""

    headers = _service(central)
    asset = f"asset:{_asset(central)}"
    body = [
        {"kind": "linkcraft.finding.opened", "subject": asset, "refs": ["signal:scenario:pv"]},
        {"kind": "linkcraft.finding.opened", "subject": "asset:no-such-asset"},
        {"kind": "histcraft.quality.changed", "subject": asset},
        {"kind": "linkcraft.finding.closed", "subject": "signal:pv", "app": "histcraft"},
        {"kind": "linkcraft.finding.closed", "subject": "signal:pv", "payload": {"n": 1}},
    ]
    response = central.post("/api/v1/events", json=body, headers=headers)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert set(receipt) == {"saved", "ids", "errors", "repeated"} and receipt["saved"] == 2
    assert receipt["repeated"] == 0
    assert all(set(item) == ERROR_FIELDS for item in receipt["errors"])
    assert [(e["index"], e["id"], e["status"]) for e in receipt["errors"]] == [
        (1, "asset:no-such-asset", 404),
        (2, asset, 422),
        (3, "signal:pv", 403),
    ]
    first, _, _, _, last = receipt["ids"]
    assert receipt["ids"][1:4] == [None, None, None] and last == first + 1
    reader = _as(central, "op")
    events = central.get("/api/v1/events", params={"after": first - 1}, headers=reader).json()
    assert [item["id"] for item in events] == [first, last]
    assert events[0]["refs"] == [asset, "signal:scenario:pv"]
    assert events[1]["subject"] == "signal:scenario:pv" and events[1]["payload"] == {"n": 1}
    assert all(set(item) == EVENT_FIELDS for item in events)
    # A person names the app in each item, as in the single form.
    person = central.post(
        "/api/v1/events",
        json=[{"kind": "linkcraft.note.added", "subject": asset, "app": "linkcraft"}],
        headers=_as(central, "eng"),
    )
    assert person.status_code == 201 and person.json()["saved"] == 1


@pytest.mark.parametrize(
    "body",
    [
        [],
        [{"kind": "linkcraft.finding.opened", "subject": "signal:scenario:pv"}] * 1001,
        [{"kind": "linkcraft.finding.opened", "subject": "signal:scenario:pv"}, 1],
        [{"kind": "linkcraft.finding.opened", "subject": "signal:scenario:pv", "refs": ["x"]}],
        [
            {
                "kind": "linkcraft.finding.opened",
                "subject": "signal:scenario:pv",
                "summary": "x" * 301,
            }
        ],
        "events",
        None,
    ],
)
def test_a_list_of_events_outside_the_shapes_is_422_for_the_whole_request(central, body):
    before = len(central.get("/api/v1/events", headers=_as(central, "op")).json())
    response = central.post("/api/v1/events", json=body, headers=_service(central))
    assert response.status_code == 422, response.text
    assert len(central.get("/api/v1/events", headers=_as(central, "op")).json()) == before


def test_a_person_posts_events_for_an_app_they_edit(central):
    body = {"kind": "linkcraft.note.added", "subject": "signal:scenario:pv"}
    assert central.post("/api/v1/events", json=body, headers=_as(central, "eng")).status_code == 422
    body["app"] = "linkcraft"
    posted = central.post("/api/v1/events", json=body, headers=_as(central, "eng"))
    assert posted.status_code == 201 and posted.json()["actor"] == "eng"
    assert central.post("/api/v1/events", json=body, headers=_as(central, "op")).status_code == 403


def test_an_event_carries_severity_key_phase_and_category(central):
    headers, reader = _service(central), _as(central, "op")
    subject = f"asset:{_asset(central)}"
    old = central.post(
        "/api/v1/events",
        json={"kind": "linkcraft.output.status", "subject": subject,
              "payload": {"severity": "Critical"}},
        headers=headers,
    ).json()  # fmt: skip
    # Written as before (severity in the payload): read with the event's own fields.
    assert (old["severity"], old["phase"], old["key"], old["category"]) == (
        "critical",
        "instant",
        "",
        "",
    )
    opened = central.post(
        "/api/v1/events",
        json={"kind": "linkcraft.finding.opened", "subject": subject, "severity": "warning",
              "phase": "start", "key": "FIC-101/oscillation", "category": "process"},
        headers=headers,
    ).json()  # fmt: skip
    assert opened["phase"] == "start" and opened["key"] == "FIC-101/oscillation"
    central.post(
        "/api/v1/events",
        json={"kind": "linkcraft.finding.closed", "subject": subject, "severity": "ok",
              "phase": "end", "key": "FIC-101/oscillation"},
        headers=headers,
    )  # fmt: skip
    found = central.get(
        "/api/v1/events", params={"key": "FIC-101/oscillation"}, headers=reader
    ).json()
    assert [(item["phase"], item["severity"]) for item in found] == [
        ("start", "warning"),
        ("end", "ok"),
    ]
    for bad in (
        {"phase": "start"},  # a condition without its key
        {"severity": "loud"},
        {"phase": "later", "key": "k"},
        {"category": "weather"},
        {"key": "x" * 201},
    ):
        body = {"kind": "linkcraft.finding.opened", "subject": subject, **bad}
        assert central.post("/api/v1/events", json=body, headers=headers).status_code == 422


def test_an_app_writes_about_itself_and_no_other_app(central):
    headers = _service(central)
    own = central.post(
        "/api/v1/events",
        json={"kind": "linkcraft.collector.stopped", "subject": "app:linkcraft"},
        headers=headers,
    )
    assert own.status_code == 201 and own.json()["subject"] == "app:linkcraft"
    other = central.post(
        "/api/v1/events",
        json={"kind": "linkcraft.collector.stopped", "subject": "app:histcraft"},
        headers=headers,
    )
    assert other.status_code == 422


CATALOG = {
    "events": [
        {"name": "finding.opened", "title": "Finding opened", "severity": "warning",
         "category": "process", "phase": "interval",
         "rule": {"when": "open", "minutes": 30, "priority": "medium"}},
        {"name": "run.failed", "title": "Run failed", "severity": "warning", "category": "run"},
    ]
}  # fmt: skip


def test_only_changes_of_a_condition_are_written(central):
    """Round 11: a start already open with the same severity, or an end of a condition not
    open, is answered with ``repeated`` and not written again; an escalation is written."""

    headers, reader = _service(central), _as(central, "op")
    subject = f"asset:{_asset(central)}"
    key = "FIC-101/stiction"

    def post(**fields):
        body = {"kind": "linkcraft.finding.opened", "subject": subject, "key": key, **fields}
        return central.post("/api/v1/events", json=body, headers=headers)

    never_opened = post(kind="linkcraft.finding.closed", phase="end", severity="ok")
    assert never_opened.status_code == 201 and never_opened.json()["repeated"] is True
    assert never_opened.json()["id"] is None
    first = post(phase="start", severity="warning").json()
    again = post(phase="start", severity="warning").json()
    assert "repeated" not in first and again["repeated"] is True and again["id"] == first["id"]
    worse = post(phase="start", severity="critical").json()
    assert "repeated" not in worse and worse["id"] > first["id"]
    receipt = central.post(
        "/api/v1/events",
        json=[
            {"kind": "linkcraft.finding.opened", "subject": subject, "key": key,
             "phase": "start", "severity": "critical"},
            {"kind": "linkcraft.finding.closed", "subject": subject, "key": key,
             "phase": "end", "severity": "ok"},
            {"kind": "linkcraft.finding.closed", "subject": subject, "key": key,
             "phase": "end", "severity": "ok"},
        ],
        headers=headers,
    ).json()  # fmt: skip
    assert receipt["saved"] == 1 and receipt["repeated"] == 2
    assert receipt["ids"][0] == worse["id"] and receipt["ids"][2] == receipt["ids"][1]
    found = central.get("/api/v1/events", params={"key": key}, headers=reader).json()
    assert [(item["phase"], item["severity"]) for item in found] == [
        ("start", "warning"),
        ("start", "critical"),
        ("end", "ok"),
    ]


def test_an_app_over_its_hourly_budget_is_refused_and_told_once(central, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_EVENT_HOURLY_LIMIT", "3")
    headers, reader = _service(central), _as(central, "op")
    subject = f"asset:{_asset(central)}"
    body = [{"kind": "linkcraft.run.failed", "subject": subject} for _ in range(5)]
    body.append(
        {"kind": "linkcraft.finding.closed", "subject": subject, "key": "k", "phase": "end"}
    )
    receipt = central.post("/api/v1/events", json=body, headers=headers).json()
    assert [(item["index"], item["status"]) for item in receipt["errors"]] == [(3, 429), (4, 429)]
    assert receipt["ids"][3:5] == [None, None]
    one = central.post("/api/v1/events", json=body[0], headers=headers)
    assert one.status_code == 429 and "changes" in one.json()["detail"]
    told = central.get(
        "/api/v1/events", params={"kind": "processcraft.events.flood"}, headers=reader
    ).json()
    assert len(told) == 1 and told[0]["subject"] == "app:linkcraft"
    assert told[0]["payload"] == {"app": "linkcraft", "limit": 3}


def test_an_app_declares_its_catalog_and_events_follow_it(central):
    headers, reader = _service(central), _as(central, "op")
    subject = f"asset:{_asset(central)}"
    put = central.put("/api/v1/events/catalog", json=CATALOG, headers=headers)
    assert put.status_code == 200 and put.json() == {"app": "linkcraft", "events": 2}
    failed = central.post(
        "/api/v1/events", json={"kind": "linkcraft.run.failed", "subject": subject},
        headers=headers,
    ).json()  # fmt: skip
    # Left out, the fields come from the catalog.
    assert (failed["severity"], failed["category"], failed["phase"]) == (
        "warning",
        "run",
        "instant",
    )
    # An interval event says start or end; an instant one neither.
    for body in (
        {"kind": "linkcraft.finding.opened", "subject": subject},
        {"kind": "linkcraft.run.failed", "subject": subject, "phase": "start", "key": "k"},
    ):
        assert central.post("/api/v1/events", json=body, headers=headers).status_code == 422
    # Undeclared: recorded, and listed in the catalog's undeclared.
    stray = central.post(
        "/api/v1/events", json={"kind": "linkcraft.stray.thing", "subject": subject},
        headers=headers,
    )  # fmt: skip
    assert stray.status_code == 201
    listed = central.get("/api/v1/events/catalog", headers=reader)
    assert listed.status_code == 200
    first, *apps = listed.json()
    assert first["app"] == "processcraft"
    kinds = {item["kind"] for item in first["events"]}
    assert {"asset.attributes_changed", "processcraft.backup.missing"} <= kinds
    [link] = [item for item in apps if item["app"] == "linkcraft"]
    assert [item["kind"] for item in link["events"]] == [
        "linkcraft.finding.opened",
        "linkcraft.run.failed",
    ]
    assert link["events"][0]["rule"]["minutes"] == 30
    assert link["undeclared"] == ["linkcraft.stray.thing"]
    # Declaring it later takes it off the list.
    again = {"events": [*CATALOG["events"], {"name": "stray.thing", "title": "Stray"}]}
    central.put("/api/v1/events/catalog", json=again, headers=headers)
    [link] = [
        item
        for item in central.get("/api/v1/events/catalog", headers=reader).json()
        if item["app"] == "linkcraft"
    ]
    assert link["undeclared"] == []


def test_a_catalog_outside_the_rules_is_422_and_only_an_app_sends_its_own(central):
    headers = _service(central)
    for body in (
        {"events": [{"name": "Bad", "title": "x"}]},
        {"events": [{"name": "a.b", "title": "x"}, {"name": "a.b", "title": "y"}]},
        {"events": [{"name": f"a.b{i}", "title": "x"} for i in range(101)]},
        {"events": [{"name": "a.b", "title": "x", "category": "process",
                     "rule": {"enabled": True}}]},
    ):  # fmt: skip
        assert central.put("/api/v1/events/catalog", json=body, headers=headers).status_code == 422
    other = {"app": "histcraft", **CATALOG}
    assert central.put("/api/v1/events/catalog", json=other, headers=headers).status_code == 403
    # A person needs editor access to the app.
    person = {"app": "linkcraft", **CATALOG}
    assert (
        central.put("/api/v1/events/catalog", json=person, headers=_as(central, "op")).status_code
        == 403
    )
    assert (
        central.put("/api/v1/events/catalog", json=person, headers=_as(central, "eng")).status_code
        == 200
    )


# Runs and schedules -------------------------------------------------------------------


def test_runs_are_upserted_per_app_and_id(central):
    headers = _service(central)
    asset = f"asset:{_asset(central)}"
    body = [
        {
            "id": "2026-10-20-0600",
            "name": "Morning round",
            "status": "running",
            "trigger": "schedule",
            "started_at": "2026-10-20T06:00:00-03:00",
            "subjects": [asset, "signal:scenario:pv", asset],
            "summary": "12 loops",
            "url": "/link/runs/2026-10-20-0600",
        },
        {"id": "manual-1", "status": "queued", "trigger": "manual", "url": "https://x.test/r/1"},
        {"id": "bad-url", "status": "done", "trigger": "api", "url": "/dash/runs/1"},
        {"id": "bad-subject", "status": "done", "trigger": "api", "subjects": ["asset:none"]},
    ]
    receipt = central.put("/api/v1/runs", json=body, headers=headers).json()
    assert receipt["saved"] == 2
    assert [(e["id"], e["status"]) for e in receipt["errors"]] == [
        ("bad-url", 422),
        ("bad-subject", 404),
    ]
    reader = _as(central, "op")
    runs = central.get("/api/v1/runs", headers=reader).json()
    assert [set(item) for item in runs] == [RUN_FIELDS, RUN_FIELDS]
    morning = next(item for item in runs if item["id"] == "2026-10-20-0600")
    assert morning["subjects"] == [asset, "signal:scenario:pv"] and morning["app"] == "linkcraft"
    assert morning["started_at"] == "2026-10-20T09:00:00.000Z"
    done = {**body[0], "status": "done", "finished_at": "2026-10-20T09:05:00Z"}
    central.put("/api/v1/runs", json=[done], headers=headers)
    assert [item["id"] for item in central.get(
        "/api/v1/runs", params={"status": "done"}, headers=reader
    ).json()] == ["2026-10-20-0600"]  # fmt: skip
    by_subject = central.get(
        "/api/v1/runs", params={"subject": "signal:scenario:pv"}, headers=reader
    )
    assert [item["id"] for item in by_subject.json()] == ["2026-10-20-0600"]
    assert central.get("/api/v1/runs", params={"app": "histcraft"}, headers=reader).json() == []
    assert len(central.get("/api/v1/runs", params={"limit": 1}, headers=reader).json()) == 1
    for params in ({"status": "sleeping"}, {"limit": 501}, {"limit": "x"}):
        assert central.get("/api/v1/runs", params=params, headers=reader).status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"trigger": None},
        {"trigger": "cron"},
        {"status": "paused"},
        {"id": ""},
        {"id": "has space"},
        {"id": "a/b"},
        {"started_at": "06:00"},
        {"subjects": "asset:x"},
        {"subjects": ["signal:scenario:pv"] * 501},
        {"url": "x" * 2001},
    ],
)
def test_runs_outside_the_contract_are_422(central, fields):
    body = {"id": "r1", "status": "done", "trigger": "api", **fields}
    body = {key: value for key, value in body.items() if value is not None}
    response = central.put("/api/v1/runs", json=[body], headers=_service(central))
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("url", "saved"),
    [
        ("/link/runs/1", True),
        ("/link", True),
        ("https://other.test/link/1", True),
        ("http://other.test:8070/x", True),
        ("", True),
        ("/dash/runs/1", False),
        ("cpm/runs/1", False),
        ("//evil.test/link/", False),
        ("/link/../api/v1/me", False),
        ("/link/a\\b", False),
        ("javascript:alert(1)", False),
        ("ftp://other.test/x", False),
        ("https://", False),
        ("/link/a b", False),
    ],
)
def test_a_url_is_a_path_under_the_app_prefix_or_http(central, url, saved):
    body = [{"id": "r1", "status": "done", "trigger": "api", "url": url}]
    receipt = central.put("/api/v1/runs", json=body, headers=_service(central)).json()
    assert (receipt["saved"] == 1) is saved, receipt


def test_schedules_replace_the_app_list(central):
    headers = _service(central)
    body = [
        {"id": "daily", "name": "Daily round", "cadence": "every day at 06:00",
         "next_run": "2026-10-21T06:00:00-03:00", "url": "/link/schedules/daily",
         "subjects": ["asset:FIC-101", "signal:TI-1"]},
        {"id": "weekly", "cadence": "every Monday", "enabled": False},
        {"id": "broken", "url": "javascript:x"},
    ]  # fmt: skip
    receipt = central.put("/api/v1/schedules", json=body, headers=headers).json()
    assert receipt["saved"] == 2 and receipt["errors"][0]["id"] == "broken"
    reader = _as(central, "op")
    listed = central.get("/api/v1/schedules", params={"app": "linkcraft"}, headers=reader).json()
    assert [set(item) for item in listed] == [SCHEDULE_FIELDS, SCHEDULE_FIELDS]
    assert [item["id"] for item in listed] == ["daily", "weekly"]
    assert listed[0]["next_run"] == "2026-10-21T09:00:00.000Z" and listed[1]["enabled"] is False
    # What each runs on (Alarms covers the assets of an execution); none when not given.
    assert listed[0]["subjects"] == ["asset:FIC-101", "signal:TI-1"] and listed[1]["subjects"] == []
    bad = central.put(
        "/api/v1/schedules", json=[{"id": "x", "subjects": ["pump"]}], headers=headers
    ).json()
    assert bad["saved"] == 0 and bad["errors"][0]["status"] == 422
    central.put("/api/v1/schedules", json=[body[1]], headers=headers)
    assert [i["id"] for i in central.get("/api/v1/schedules", headers=reader).json()] == ["weekly"]
    duplicate = central.put("/api/v1/schedules", json=[body[1], body[1]], headers=headers)
    assert duplicate.status_code == 422
    assert central.put("/api/v1/schedules", json=[], headers=headers).json()["saved"] == 0
    assert central.get("/api/v1/schedules", headers=reader).json() == []
    # A person names the app in the query and needs editor access to it.
    engineer = _as(central, "eng")
    assert central.put("/api/v1/schedules", json=[], headers=engineer).status_code == 422
    allowed = central.put("/api/v1/schedules?app=linkcraft", json=[body[0]], headers=engineer)
    assert allowed.json()["saved"] == 1
    refused = central.put("/api/v1/schedules?app=linkcraft", json=[], headers=_as(central, "op"))
    assert refused.status_code == 403
    assert central.put(
        "/api/v1/schedules?app=histcraft", json=[], headers=headers
    ).status_code == 403  # fmt: skip


# Hostile input and the fake --------------------------------------------------------------

JUNK_BODIES = [None, {}, [], "not json", [None], [{}], {"name": "x" * 10_000}, [[]], 42, [1.5]]
JUNK_QUERY = {
    "subject": "x" * 500, "app": "'; DROP TABLE app_results;--", "kind": "%00", "status": "ç☃",
    "after": "NaN", "limit": "-5", "ref": "../../etc/passwd",
}  # fmt: skip
LINK_ROUTES = [
    ("PUT", "/api/v1/results"),
    ("GET", "/api/v1/results"),
    ("GET", "/api/v1/results/history"),
    ("POST", "/api/v1/events"),
    ("GET", "/api/v1/events"),
    ("PUT", "/api/v1/runs"),
    ("GET", "/api/v1/runs"),
    ("PUT", "/api/v1/schedules"),
    ("GET", "/api/v1/schedules"),
    ("PUT", "/api/v1/events/catalog"),
    ("GET", "/api/v1/events/catalog"),
]


def test_every_link_route_answers_junk_without_a_server_error(central):
    """Hostile input with a valid token (the generic hostile test stops at the 401)."""

    tokens = {"service": _service(central), "editor": _as(central, "eng")}
    failures = []
    for headers in tokens.values():
        for method, path in LINK_ROUTES:
            bodies = JUNK_BODIES if method != "GET" else [None]
            for body in bodies:
                for params in ({}, JUNK_QUERY):
                    kwargs = {"params": params, "headers": dict(headers)}
                    if isinstance(body, str):
                        kwargs["content"] = body
                        kwargs["headers"]["Content-Type"] = "application/json"
                    elif body is not None:
                        kwargs["json"] = body
                    response = central.request(method, path, **kwargs)
                    if response.status_code >= 500:
                        failures.append(f"{method} {path} {body!r:.30} -> {response.status_code}")
    assert not failures, "\n".join(failures)


def test_the_fake_serves_the_same_shapes(central):
    """Apps test their links against FakePlantCraft: its answers look like PlantCraft's."""

    asset = _asset(central)

    def shapes(client, asset_id, signal_id):
        subject = f"asset:{asset_id}"
        put = client.put_results(
            [
                {"subject": subject, "kind": "loop_health", "status": "ok", "score": 90},
                {"subject": "asset:none", "kind": "loop_health", "status": "ok"},
            ]
        )
        event = client.post_event("linkcraft.finding.opened", subject, refs=[f"signal:{signal_id}"])
        many = client.post_events(
            [
                {"kind": "linkcraft.finding.closed", "subject": subject},
                {"kind": "linkcraft.finding.closed", "subject": "asset:none"},
                {"kind": "linkcraft.finding.opened", "subject": f"signal:{signal_id}"},
            ]
        )
        runs = client.put_runs(
            [{"id": "r1", "status": "done", "trigger": "api", "subjects": [subject],
              "url": "/link/runs/r1"}]
        )  # fmt: skip
        schedules = client.put_schedules([{"id": "daily", "cadence": "every day"}])
        catalog = client.put_event_catalog(CATALOG["events"])
        declared = [item for item in client.event_catalog() if item["app"] == "linkcraft"]
        return {
            "catalog": (catalog, [set(item) for item in declared[0]["events"]]),
            "put": (set(put), put["saved"], {frozenset(item) for item in put["errors"]}),
            "results": [set(item) for item in client.results([subject])],
            "history": [set(item) for item in client.result_history(subject)],
            "event": set(event),
            "many": (
                set(many),
                many["saved"],
                [item is None for item in many["ids"]],
                [(item["index"], item["status"], set(item)) for item in many["errors"]],
            ),
            "both": len(client.results([subject, f"signal:{signal_id}"])),
            "events": [set(item) for item in client.events(ref=subject)],
            "runs": (set(runs), [set(item) for item in client.runs(subject=subject)]),
            "schedules": (set(schedules), [set(item) for item in client.schedules()]),
            "errors": put["errors"][0]["status"],
        }

    key = _app_key(central)["key"]
    real = PlantCraftClient("http://testserver", app="linkcraft", key=key, http_client=central)
    fake = FakePlantCraft()
    faked = fake.client(None, app="linkcraft", key="test-app-key")
    assert shapes(real, asset, "scenario:pv") == shapes(faked, "fic-101", "fake:FIC-101.PV")
    # A person's client names the app itself.
    person = PlantCraftClient(
        "http://testserver", _token(central, "eng"), app="linkcraft", http_client=central
    )
    assert person.put_results([_result()])["saved"] == 1


# What each app adds (docs/app-standard.md, section 4b) -------------------------------

CONTRIBUTIONS = {
    "version": "0.1.0",
    "contributes": {
        "llm": [{"id": "algorithm-draft", "title": "Draft an algorithm"}],
        "widgets": [{"id": "worst-assets", "title": "Worst assets", "default": True}],
        "queue": True,
    },
    "series": [{"name": "{schedule}.{output}", "title": "Outputs", "retention": "app"}],
    "events": CATALOG["events"],
}


def test_an_app_sends_what_it_adds_and_every_screen_reads_it(central):
    headers, reader = _service(central), _as(central, "op")
    put = central.put("/api/v1/contributions", json=CONTRIBUTIONS, headers=headers)
    assert put.status_code == 200
    assert put.json() == {"app": "linkcraft", "events": 2, "unknown": []}
    # The events reach the catalog with the rest.
    [link] = [
        item
        for item in central.get("/api/v1/events/catalog", headers=reader).json()
        if item["app"] == "linkcraft"
    ]
    assert [item["kind"] for item in link["events"]] == [
        "linkcraft.finding.opened",
        "linkcraft.run.failed",
    ]
    listed = central.get("/api/v1/contributions", headers=reader).json()
    assert "llm" in listed["features"] and "series" in listed["features"]
    [item] = listed["apps"]
    assert item["app"] == "linkcraft" and item["version"] == "0.1.0"
    assert item["contributes"]["llm"][0]["default"] == "default"
    assert item["series"][0]["retention"] == "app"
    installation = central.get("/api/v1/installation", headers=reader).json()
    assert installation["features"] == listed["features"]
    # Replaced whole; a table this PlantCraft does not know is set aside, not refused.
    newer = {"contributes": {"hologram": [{"id": "x"}]}}
    put = central.put("/api/v1/contributions", json=newer, headers=headers)
    assert put.status_code == 200 and put.json()["unknown"] == ["hologram"]
    [item] = central.get("/api/v1/contributions", headers=reader).json()["apps"]
    assert item["contributes"].get("llm", []) == [] and item["unknown"] == ["hologram"]


def test_contributions_outside_the_rules_are_422_and_only_an_app_sends_its_own(central):
    headers = _service(central)
    for body in (
        {"contributes": {"llm": [{"id": "Bad", "title": "x"}]}},
        {"contributes": {"refs": [{"kind": "asset", "title": "x", "url": "/link/{id}"}]}},
        {"series": [{"name": "a", "title": "x", "type": "image"}]},
    ):
        assert central.put("/api/v1/contributions", json=body, headers=headers).status_code == 422
    other = {"app": "histcraft", **CONTRIBUTIONS}
    assert central.put("/api/v1/contributions", json=other, headers=headers).status_code == 403
    person = {"app": "linkcraft", **CONTRIBUTIONS}
    assert (
        central.put("/api/v1/contributions", json=person, headers=_as(central, "op")).status_code
        == 403
    )
