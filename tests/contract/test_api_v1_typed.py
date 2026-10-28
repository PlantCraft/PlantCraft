"""API v1 typed derived points and runs points (docs/api-v1.md, "Derived series").

A derived point holds one kind of value: number, integer, boolean, text, instant or
structured; the writing app may set its retention (0 keeps it forever) and lock it
(``managed_by``). A runs point keeps one whole series per execution, the newest ``keep_runs``.
PlantCraft without a Historian and ``FakePlantCraft`` answer the same shapes.
"""

from __future__ import annotations

import pytest

from plantcraft_sdk.client import Forbidden
from plantcraft_sdk.testing import FakePlantCraft
from tests.contract.test_api_v1 import _as
from tests.contract.test_api_v1_derived import _service

T = ["2026-10-19T06:00:00Z", "2026-10-19T07:00:00Z"]
WINDOW = {"start": "2026-10-19T05:00:00Z", "end": "2026-10-19T09:00:00Z"}
UTC = ["2026-10-19T06:00:00+00:00", "2026-10-19T07:00:00+00:00"]
TYPED = [
    ("integer", [3, 4.0], [3, 4]),
    ("boolean", [True, False], [True, False]),
    ("instant", ["2026-10-19T08:00:00-03:00", None], ["2026-10-19T11:00:00+00:00", None]),
    (
        "structured",
        [{"loops": ["FIC-1"], "score": 2.5}, [1, 2]],
        [{"loops": ["FIC-1"], "score": 2.5}, [1, 2]],
    ),
]


def _run(signal: str, run_at: str, values: list[float], **fields) -> dict:
    stamps = [f"2026-10-20T0{hour}:00:00Z" for hour in range(len(values))]
    return {"signal": signal, "run_at": run_at, "t": stamps, "v": values, **fields}


@pytest.mark.parametrize(("kind", "sent", "read"), TYPED)
def test_typed_points_come_back_as_written(central, kind, sent, read):
    signal = f"app-linkcraft:fic-1.daily.{kind}"
    item = {
        "signal": signal,
        "kind": kind,
        "t": T,
        "v": sent,
        "retention_days": 0,
        "managed_by": "link:daily",
    }
    answer = central.put("/api/v1/series", json=[item], headers=_service(central))
    assert answer.json() == {"written": 1, "errors": []}, answer.text
    reader = _as(central, "op")
    series = central.get(f"/api/v1/signals/{signal}/series", params=WINDOW, headers=reader).json()
    assert series == {"signal": signal, "kind": kind, "t": UTC, "v": read}
    shape = central.get(f"/api/v1/signals/{signal}", headers=reader).json()
    assert (shape["kind"], shape["managed_by"], shape["retention_days"]) == (kind, "link:daily", 0)
    batch = central.post(
        "/api/v1/series", json={"signals": [signal], **WINDOW}, headers=reader
    ).json()
    assert batch["series"][0]["v"] == read
    mean = central.get(f"/api/v1/signals/{signal}/value", params={"agg": "mean"}, headers=reader)
    assert mean.status_code == 422


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("integer", 2.5),
        ("integer", True),
        ("boolean", 1),
        ("instant", "soon"),
        ("structured", "x"),
        ("number", float("inf")),
    ],
)
def test_values_outside_their_kind_are_refused(central, kind, value):
    item = {"signal": "app-linkcraft:x", "kind": kind, "t": T[:1], "v": [value]}
    if value == float("inf"):
        item["v"] = ["inf"]  # JSON has no infinity: a text in a number point
    answer = central.put("/api/v1/series", json=[item], headers=_service(central))
    assert answer.status_code == 422 and answer.json()["detail"].startswith("[0] ")


def test_a_runs_point_keeps_the_newest_executions(central):
    signal = "app-linkcraft:fic-1.daily.forecast"
    headers = _service(central)
    for day in range(1, 5):
        run = _run(signal, f"2026-10-2{day}T00:00:00Z", [day, day + 0.5], keep_runs=3, unit="m3/h")
        assert central.put("/api/v1/series/runs", json=[run], headers=headers).json() == {
            "written": 1,
            "errors": [],
        }
    # The same run time again replaces that run.
    again = _run(signal, "2026-10-24T00:00:00Z", [9.0], keep_runs=3)
    central.put("/api/v1/series/runs", json=[again], headers=headers)
    reader = _as(central, "op")
    url = f"/api/v1/signals/{signal}/series"
    latest = central.get(url, headers=reader).json()
    assert latest["kind"] == "runs" and [run["run_at"] for run in latest["runs"]] == [
        "2026-10-24T00:00:00+00:00"
    ]
    assert latest["runs"][0]["v"] == [9.0]
    three = central.get(url, params={"runs": 5}, headers=reader).json()["runs"]
    assert [run["run_at"][:10] for run in three] == ["2026-10-24", "2026-10-23", "2026-10-22"]
    one = central.get(url, params={"run": "2026-10-22T00:00:00Z"}, headers=reader).json()["runs"]
    assert one[0]["v"] == [2.0, 2.5] and one[0]["t"][0] == "2026-10-20T00:00:00+00:00"
    listed = central.get(f"/api/v1/signals/{signal}/runs", headers=reader).json()
    assert listed["runs"][0] == {
        "run_at": "2026-10-24T00:00:00+00:00",
        "start": "2026-10-20T00:00:00+00:00",
        "end": "2026-10-20T00:00:00+00:00",
        "n": 1,
    }
    batch = central.post("/api/v1/series", json={"signals": [signal]}, headers=reader).json()
    assert batch["series"][0]["run_at"] == "2026-10-24T00:00:00+00:00"
    shape = central.get(f"/api/v1/signals/{signal}", headers=reader).json()
    assert (shape["kind"], shape["unit"]) == ("runs", "m3/h")
    assert central.get(f"/api/v1/signals/{signal}/value", headers=reader).status_code == 422
    # A runs point takes no plain values, a plain point no runs.
    plain = {"signal": signal, "t": T[:1], "v": [1]}
    assert central.put("/api/v1/series", json=[plain], headers=headers).json()["errors"]
    other = "app-linkcraft:plain"
    central.put("/api/v1/series", json=[{**plain, "signal": other}], headers=headers)
    refused = central.put("/api/v1/series/runs", json=[_run(other, T[0], [1])], headers=headers)
    assert refused.json()["errors"][0]["status"] == 409
    assert central.get(f"/api/v1/signals/{other}/runs", headers=reader).status_code == 422


def test_only_an_app_writes_runs_and_only_its_own(central):
    run = _run("app-linkcraft:f", T[0], [1])
    assert (
        central.put("/api/v1/series/runs", json=[run], headers=_as(central, "eng")).status_code
        == 403
    )
    other = central.put("/api/v1/series/runs", json=[run], headers=_service(central, "dashcraft"))
    assert other.status_code == 403
    broken = central.put(
        "/api/v1/series/runs", json=[{**run, "keep_runs": 0}], headers=_service(central)
    )
    assert broken.status_code == 422 and broken.json()["detail"].startswith("[0] keep_runs")


def test_the_client_and_the_fake_answer_typed_and_runs_points_alike(central):
    from plantcraft_sdk.client import PlantCraftClient
    from tests.contract.test_api_v1 import _app_key

    real = PlantCraftClient(
        "http://testserver",
        app="linkcraft",
        key=_app_key(central, "linkcraft")["key"],
        http_client=central,
    )
    fake = FakePlantCraft().client(None, app="linkcraft", key="test-app-key")
    signal = "app-linkcraft:fic-1.daily.forecast"
    flags = "app-linkcraft:fic-1.daily.flags"
    answers = []
    for client in (real, fake):
        client.put_series(
            [
                {
                    "signal": flags,
                    "kind": "structured",
                    "t": T,
                    "v": [{"a": 1}, None],
                    "managed_by": "link:daily",
                }
            ]
        )
        for day in (1, 2, 3):
            client.put_series_runs([_run(signal, f"2026-10-2{day}T00:00:00Z", [day], keep_runs=2)])
        answers.append(
            (
                client.series(flags, *WINDOW.values()),
                client.series_runs(signal),
                client.series_runs(signal, last=5),
                client.series_runs(signal, run="2026-10-22T00:00:00Z"),
                client.series_run_list(signal),
                {
                    key: client.signal(flags)[key]
                    for key in ("kind", "managed_by", "retention_days")
                },
            )
        )
    assert answers[0] == answers[1]
    series, latest, newest, chosen, listed, shape = answers[0]
    assert series["v"] == [{"a": 1}, None] and shape["managed_by"] == "link:daily"
    assert [run["v"] for run in newest] == [[3.0], [2.0]] and latest == newest[:1]
    assert chosen[0]["run_at"] == "2026-10-22T00:00:00+00:00" and len(listed) == 2
    with pytest.raises(Forbidden):
        FakePlantCraft().client("admin").put_series_runs([_run(signal, T[0], [1])])
