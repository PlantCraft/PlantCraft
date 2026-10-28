"""The Overview's widgets about the whole plant (owner, 2026-10-27): the loops and signals in
alarm on each of the last 14 days, and the health map, one square per loop and signal by area."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk import widgets as w
from plantcraft_sdk.asset_scope import forget
from plantcraft_sdk.utc import utc_iso

from linkcraft.api import plant_widgets
from linkcraft.api.app import create_app
from linkcraft.api.routers.results import signal_label
from linkcraft.data.frames import loop_signal_ids
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND


@pytest.fixture(autouse=True)
def _fresh():
    forget()
    yield
    forget()


def _noon(days_ago: int) -> str:
    """Midday ``days_ago`` days back, on the installation's clock."""

    bounds = plant_widgets.day_bounds()
    return utc_iso(bounds[-2 - days_ago] + timedelta(hours=12))


def test_nothing_judged_yet_reads_as_empty(client):
    history = client.get("/link/api/widgets/in-alarm-history").json()
    assert history["kind"] == "columns" and history["step"] == "day"
    assert history["buckets"] == [] and history["empty"]
    assert [stack["state"] for stack in history["stacks"]] == ["alarm", "warning"]
    health = client.get("/link/api/widgets/health-map").json()
    assert health["kind"] == "tiles" and health["empty"]


def test_the_health_map_shows_every_loop_by_area(client, analysed, monkeypatch):
    health = client.get("/link/api/widgets/health-map").json()
    assert health["kind"] == "tiles" and health.get("more") is None
    squares = {tile["label"]: tile for group in health["groups"] for tile in group["tiles"]}
    loops = client.get("/link/api/results?kind=loop").json()["items"]
    assert {row["id"] for row in loops} <= set(squares)
    lic = squares["lic-102"]
    assert lic["state"] == "alarm" and lic["href"] == "/link/loops/lic-102" and lic["detail"]
    # The loops sit in their parent asset's group, PlantCraft's "Area A".
    area = next(group for group in health["groups"] if group["label"] == "Area A")
    assert "lic-102" in {tile["label"] for tile in area["tiles"]}
    # Within an area the worst come first.
    ranks = [plant_widgets.RANK[tile["state"]] for tile in area["tiles"]]
    assert ranks == sorted(ranks)
    assert health["value"] == sum(len(group["tiles"]) for group in health["groups"])
    # Past the cap the squares in alarm and in warning stay; the card counts the rest.
    monkeypatch.setattr(w, "MAX_TILES", 2)
    health = client.get("/link/api/widgets/health-map").json()
    kept = [tile for group in health["groups"] for tile in group["tiles"]]
    assert len(kept) == 2 and health["more"] == health["value"] - 2
    assert {tile["state"] for tile in kept} <= {"alarm", "warning"}


def test_the_days_in_alarm_count_each_subject_once_a_day(client, analysed):
    runtime = analysed
    loops = [row["id"] for row in client.get("/link/api/results?kind=loop").json()["items"]]
    first, second = loops[:2]
    rows = [
        # Two days ago: one loop ended the day in alarm (after a warning), one in warning.
        {"subject_id": first, "source_end": _noon(2), "status": "medium", "health": 60},
        {"subject_id": first, "source_end": _noon(2)[:11] + "20:00:00Z", "status": "high"},
        {"subject_id": second, "source_end": _noon(2), "status": "medium", "health": 55},
        # Yesterday: both fine.
        {"subject_id": first, "source_end": _noon(1), "status": "normal", "health": 90},
        {"subject_id": second, "source_end": _noon(1), "status": "normal", "health": 90},
        # A loop no longer here is not counted.
        {"subject_id": "gone-1", "source_end": _noon(1), "status": "critical", "health": 5},
    ]
    runtime.latest.add_history(APPLICATION_ID, SUBJECT_KIND, rows)
    plant_widgets._PAST.pop(runtime, None)
    history = client.get("/link/api/widgets/in-alarm-history").json()
    buckets = history["buckets"]
    assert len(buckets) == plant_widgets.DAYS
    assert [start for start, _ in buckets] == sorted(start for start, _ in buckets)
    assert buckets[-3][1] == [1, 1]
    assert buckets[-2][1] == [0, 0]
    # A day without any verdict is an empty column, not a zero.
    assert buckets[0][1] == [None, None]
    # Today is the status now, as Results says it.
    now = client.get("/link/api/results?kind=loop").json()["items"]
    alarms = sum(1 for row in now if row["status"] == "alarm")
    assert buckets[-1][1] == [alarms, sum(1 for row in now if row["status"] == "warning")]
    assert history["value"] == alarms and history["state"] == "alarm"
    assert history["href"] == "/link/results?status=alarm,warning"


def test_the_days_in_alarm_keep_to_the_part_a_person_sees(analysed, fake):
    runtime = analysed
    runtime.latest.add_history(
        APPLICATION_ID,
        SUBJECT_KIND,
        [
            {"subject_id": "lic-102", "source_end": _noon(1), "status": "high", "health": 20},
            {"subject_id": "fic-101", "source_end": _noon(1), "status": "high", "health": 20},
        ],
    )
    plant_widgets._PAST.pop(runtime, None)
    with TestClient(create_app(runtime), raise_server_exceptions=False) as operator:
        operator.headers["Authorization"] = f"Bearer {fake.token('operator', assets=['lic-102'])}"
        history = operator.get("/link/api/widgets/in-alarm-history").json()
        assert history["buckets"][-2][1] == [1, 0]
        health = operator.get("/link/api/widgets/health-map").json()
        labels = {tile["label"] for group in health["groups"] for tile in group["tiles"]}
        assert "lic-102" in labels and "fic-101" not in labels


def test_the_health_map_shows_assets_by_area_not_loops_apart(client, analysed):
    """An algorithm's result on an asset is a square of its area too: loops are only one type
    of asset, not a group of their own (owner, 2026-10-27)."""

    runtime = analysed
    algorithm = runtime.presets.list_profiles()[0]
    runtime.asset_runs.save(
        algorithm["profile_id"],
        "lic-102",
        asset_name="LIC-102 drum",
        summary={"verdict": {"status": "bad", "value": 12.0, "message": "Fouling"}},
        states={},
        written={},
        window_end=None,
    )
    health = client.get("/link/api/widgets/health-map").json()
    assert health["label"] == "assets and signals"
    area = next(group for group in health["groups"] if group["label"] == "Area A")
    square = next(tile for tile in area["tiles"] if tile["label"] == "LIC-102 drum")
    assert square["state"] == "alarm" and square["href"] == "/link/assets/lic-102"
    assert square["detail"].startswith(f"{algorithm['name']}: ")


def test_a_loops_signals_sit_in_the_loops_area(analysed):
    """Its SP and mode too, which no asset holds: no big "No area" block of loop signals."""

    loops, signals, _ = plant_widgets._areas(analysed)
    assert loops
    for loop in analysed.loops.list_loops():
        if loop.loop_id in loops:
            for signal in loop_signal_ids(loop):
                assert signals[signal] == loops[loop.loop_id]
    row = {"kind": "signal", "id": f"plant:{signal}", "caption": ""}
    assert plant_widgets._where(row, (loops, signals, {})) == signals[signal]


def test_a_signal_reads_as_its_loop_and_role():
    assert signal_label("plantcraft:CPM.Loops.AIC-1006.OP") == "AIC-1006 · OP"
    assert signal_label("TI-100.PV") == "TI-100 · PV"
    assert signal_label("lab:LAB-U100.DIESEL.DENSITY") == "LAB-U100.DIESEL.DENSITY"
    assert signal_label("plant:Area/1/TT") == "Area/1/TT"
