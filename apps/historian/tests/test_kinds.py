"""Point kinds beyond number and text, "keep forever" and points an app manages (H1)."""

from __future__ import annotations

import pytest

from histcraft.archive.store import ArchiveStore, now_ms
from histcraft.catalog.models import CatalogError, PointPatch
from histcraft.collector.service import Collector
from histcraft.db import Database
from histcraft.kinds import coerce, outward
from tests.test_api import DATA, pc  # noqa: F401 - the PlantCraft client fixture

T = ["2026-10-19T00:00:00Z", "2026-10-19T00:10:00Z", "2026-10-19T00:20:00Z"]
RANGE = {"start": "2026-10-19T00:00:00Z", "end": "2026-10-19T00:30:00Z"}


def _write(client, signal, kind, values, **extra):
    item = {"signal": signal, "kind": kind, "t": T[: len(values)], "v": values, **extra}
    return client.post(f"{DATA}/derived", json={"app": "linkcraft", "series": [item]}).json()


@pytest.mark.parametrize(
    ("kind", "values", "read"),
    [
        ("integer", [3, None, 5], [3, 5]),
        ("boolean", [True, False, None], [True, False]),
        (
            "instant",
            ["2026-10-18T21:00:00-03:00", None, "2026-10-19T00:05:00Z"],
            ["2026-10-19T00:00:00+00:00", "2026-10-19T00:05:00+00:00"],
        ),
        ("structured", [{"a": 1, "b": [1, 2]}, None, [1, "x"]], [{"a": 1, "b": [1, 2]}, [1, "x"]]),
        ("text", ["ok", None, "late"], ["ok", "late"]),
    ],
)
def test_each_kind_is_written_and_read_back_typed(pc, kind, values, read):  # noqa: F811
    signal = f"app-linkcraft:out.{kind}"
    assert _write(pc, signal, kind, values) == {"written": 3, "errors": []}
    recorded = pc.get(f"{DATA}/signals/{signal}/series", params=RANGE).json()
    assert recorded["kind"] == kind and recorded["v"] == read
    # On a grid: the value in effect at the end of each cell, never a mean.
    grid = pc.get(f"{DATA}/signals/{signal}/series", params={**RANGE, "step": 600}).json()
    assert grid["v"][0] == read[0]
    batch = pc.post(f"{DATA}/series", json={"signals": [signal], **RANGE}).json()
    assert batch["series"][0]["v"] == read
    last = pc.get(f"{DATA}/signals/{signal}/value", params={"window": "366d"}).json()
    # The newest value read; a gap last means nothing is known now.
    assert last["value"] == (None if values[-1] is None else read[-1])


def test_wrong_values_and_kind_changes_are_refused(pc):  # noqa: F811
    assert _write(pc, "app-linkcraft:n", "integer", [1.5])["errors"][0]["status"] == 422
    assert _write(pc, "app-linkcraft:b", "boolean", [1])["errors"][0]["status"] == 422
    assert (
        _write(pc, "app-linkcraft:i", "instant", ["2026-10-19T00:00:00"])["errors"][0]["status"]
        == 422
    )
    assert _write(pc, "app-linkcraft:s", "structured", ["text"])["errors"][0]["status"] == 422
    assert _write(pc, "app-linkcraft:k", "other", [1])["errors"][0]["status"] == 422
    assert _write(pc, "app-linkcraft:x", "integer", [1])["written"] == 1
    assert _write(pc, "app-linkcraft:x", "number", [1.0])["errors"][0]["status"] == 409


def test_coerce_and_outward_round_trip():
    assert coerce("integer", 4.0) == 4.0 and outward("integer", [4.0, None]) == [4, None]
    assert outward("boolean", [1.0, 0.0]) == [True, False]
    assert outward("structured", ['{"a": 1}']) == [{"a": 1}]  # a SQLite snapshot
    assert len(coerce("text", "x" * 5000)) == 1000


def test_an_app_sets_retention_forever_and_locks_it(pc, runtime, client):  # noqa: F811
    signal = "app-linkcraft:FIC-101.index"
    answer = _write(pc, signal, "number", [1.0], retention_days=0, managed_by="link:daily")
    assert answer == {"written": 1, "errors": []}
    found = pc.get(f"{DATA}/signals/{signal}").json()
    assert found["retention_days"] == 0 and found["managed_by"] == "link:daily"
    # People cannot change what the app sets, here or through the catalog.
    response = client.patch(f"/hist/api/points/{signal}", json={"retention_days": 30})
    assert response.status_code == 409 and "link:daily" in response.json()["detail"]
    with pytest.raises(CatalogError):
        runtime.catalog.update_point(signal, PointPatch(deviation=1.0))
    assert client.patch(f"/hist/api/points/{signal}", json={"name": "Index"}).status_code == 200
    # A later write without them leaves both as they are; the app changes them by sending them.
    _write(pc, signal, "number", [2.0])
    assert pc.get(f"{DATA}/signals/{signal}").json()["retention_days"] == 0
    _write(pc, signal, "number", [2.0], retention_days=400)
    assert pc.get(f"{DATA}/signals/{signal}").json()["retention_days"] == 400


def test_housekeeping_keeps_a_forever_point(runtime, pc, monkeypatch):  # noqa: F811
    _write(pc, "app-linkcraft:keep", "number", [1.0], retention_days=0)
    _write(pc, "app-linkcraft:short", "number", [1.0], retention_days=5)
    archive = ArchiveStore(Database(runtime.settings.archive_target))
    seen: dict[int, int] = {}
    monkeypatch.setattr(archive, "prune", lambda cutoffs, levels=None: seen.update(cutoffs) or 0)
    before = now_ms()
    Collector(runtime.settings, runtime.catalog, archive).housekeeping(force=True)
    keep = runtime.catalog.point("app-linkcraft:keep")["id"]
    short = runtime.catalog.point("app-linkcraft:short")["id"]
    assert keep not in seen
    assert round((before - seen[short]) / 86_400_000) == 5


# Runs (H2) -----------------------------------------------------------------------------------


def _run(client, run_at, values, signal="app-linkcraft:FIC-101.response", **extra):
    times = [f"2026-10-19T0{run_at}:{minute:02d}:00Z" for minute in range(len(values))]
    item = {"signal": signal, "run_at": f"2026-10-19T0{run_at}:30:00Z", "t": times, "v": values}
    body = {"app": "linkcraft", "series": [{**item, **extra}]}
    return client.post(f"{DATA}/derived/runs", json=body).json()


def test_runs_keep_one_series_per_execution(pc, client):  # noqa: F811
    signal = "app-linkcraft:FIC-101.response"
    for hour in range(1, 5):
        answer = _run(pc, hour, [hour, hour + 0.5, None], keep_runs=3, managed_by="link:daily")
        assert answer == {"written": 1, "errors": []}
    # The same run time again replaces that run.
    assert _run(pc, 4, [9.0], keep_runs=3)["written"] == 1
    listed = pc.get(f"{DATA}/signals/{signal}/runs").json()["runs"]
    assert [r["run_at"] for r in listed] == [
        "2026-10-19T04:30:00+00:00",
        "2026-10-19T03:30:00+00:00",
        "2026-10-19T02:30:00+00:00",
    ]
    assert listed[0]["n"] == 1 and listed[1]["start"] == "2026-10-19T03:00:00+00:00"
    found = pc.get(f"{DATA}/signals/{signal}").json()
    assert found["kind"] == "runs" and found["managed_by"] == "link:daily"
    assert found["retention_days"] == 0  # by count only
    latest = pc.get(f"{DATA}/signals/{signal}/series").json()
    assert latest == {
        "signal": signal,
        "kind": "runs",
        "runs": [
            {"run_at": "2026-10-19T04:30:00+00:00", "t": ["2026-10-19T04:00:00+00:00"], "v": [9.0]}
        ],
    }
    one = pc.get(f"{DATA}/signals/{signal}/series", params={"run": "2026-10-19T02:30:00Z"}).json()
    assert one["runs"][0]["v"] == [2.0, 2.5, None]
    several = pc.get(f"{DATA}/signals/{signal}/series", params={"runs": 5}).json()["runs"]
    assert len(several) == 3
    assert pc.get(f"{DATA}/signals/{signal}/series", params={"runs": 60}).status_code == 422
    batch = pc.post(f"{DATA}/series", json={"signals": [signal]}).json()["series"][0]
    assert batch["kind"] == "runs" and batch["run_at"] == "2026-10-19T04:30:00+00:00"
    assert batch["v"] == [9.0]
    # The pages read them the same way, and count what is kept.
    page = client.get(f"/hist/api/points/{signal}/series", params={"runs": 2}).json()
    assert [r["run_at"][:13] for r in page["runs"]] == ["2026-10-19T04", "2026-10-19T03"]
    assert len(client.get(f"/hist/api/points/{signal}/runs").json()["runs"]) == 3


def test_runs_refuse_other_kinds_and_bad_runs(pc):  # noqa: F811
    assert _write(pc, "app-linkcraft:plain", "number", [1.0])["written"] == 1
    assert _run(pc, 1, [1.0], signal="app-linkcraft:plain")["errors"][0]["status"] == 409
    assert _write(pc, "app-linkcraft:FIC-101.response", "runs", [1.0])["errors"][0]["status"] == 422
    bad = {"signal": "app-linkcraft:r", "run_at": "soon", "t": [], "v": []}
    answer = pc.post(f"{DATA}/derived/runs", json={"app": "linkcraft", "series": [bad]}).json()
    assert answer["errors"][0]["status"] == 422
    many = {"signal": "app-linkcraft:r", "run_at": "2026-10-19T00:00:00Z", "t": ["x"] * 20_001}
    many["v"] = [1] * 20_001
    response = pc.post(f"{DATA}/derived/runs", json={"app": "linkcraft", "series": [many]})
    assert response.status_code == 422


def test_runs_are_pruned_by_age_when_the_app_says_so(runtime, pc):  # noqa: F811
    _run(pc, 1, [1.0], keep_days=5)
    point = runtime.catalog.point("app-linkcraft:FIC-101.response")
    assert point["retention_days"] == 5
    runtime.archive.prune({int(point["id"]): to_ms_iso("2026-10-19T02:00:00Z")})
    assert runtime.archive.run_list(int(point["id"])) == []
    runtime.archive.delete_points([int(point["id"])])


def to_ms_iso(text):
    from datetime import datetime

    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
