"""H5: interpolated reads with a maximum interpolation interval, and a window's summary (count,
time covered, % good, total), on the data routes PlantCraft's API v1 forwards to."""

from __future__ import annotations

import numpy as np
import pytest

from histcraft.archive.query import _interpolate, to_ms
from histcraft.catalog.models import PointIn, SourceIn
from tests.test_api import DATA, pc  # noqa: F401 - the fixture
from tests.test_query import T0

MS = to_ms(T0)
START, END = "2026-10-19T00:00:00Z", "2026-10-19T01:00:00Z"


@pytest.fixture
def plant(runtime):
    runtime.catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://127.0.0.1:4840/"), create=True
    )
    runtime.catalog.add_points(
        [
            PointIn(tag="FI-1.PV", source_id="plant", address="ns=2;s=FI-1.PV", unit="t/h"),
            PointIn(tag="XV-1.POS", source_id="plant", address="ns=2;s=XV-1.POS", step=True),
            PointIn(tag="FIC-1.MODE", source_id="plant", address="ns=2;s=FIC-1.MODE", kind="text"),
        ]
    )
    points = {p["tag"]: p["id"] for p in runtime.catalog.points()}
    runtime.archive.append(
        {
            # 0 at 00:00, 60 at 00:10, then nothing until 60 again at 00:50 (a 40-minute gap).
            points["FI-1.PV"]: (
                "number",
                [(MS, 0.0), (MS + 600_000, 60.0), (MS + 3_000_000, 60.0)],
            ),
            points["XV-1.POS"]: (
                "number",
                [(MS, 0.0), (MS + 1_800_000, 1.0), (MS + 3_600_000, 1.0)],
            ),
            points["FIC-1.MODE"]: ("text", [(MS, "AUTO")]),
        }
    )
    # Uncertain from 00:15 to 00:30, then good again.
    runtime.archive.put_qualities(
        [
            (points["FI-1.PV"], MS + 900_000, "uncertain"),
            (points["FI-1.PV"], MS + 1_800_000, "good"),
        ]
    )
    return runtime


def test_interpolated_values_lie_on_the_line_between_samples(pc, plant):  # noqa: F811
    url = f"{DATA}/signals/plant:FI-1.PV/series"
    answer = pc.get(
        url, params={"start": START, "end": END, "step": 300, "sampling": "interpolated"}
    ).json()
    # Grid times 00:00, 00:05, ... 01:00 inclusive: 13 values.
    assert len(answer["t"]) == 13 and answer["t"][1] == "2026-10-19T00:05:00+00:00"
    assert answer["v"][:3] == [0.0, 30.0, 60.0]
    assert answer["v"][6] == pytest.approx(60.0)
    # Past the last sample (00:50) nothing is known.
    assert answer["v"][10] == 60.0 and answer["v"][11] is None and answer["v"][12] is None
    averaged = pc.get(url, params={"start": START, "end": END, "step": 300}).json()
    assert averaged["v"][0] == pytest.approx(15.0) and len(averaged["v"]) == 12


def test_a_gap_longer_than_max_gap_is_not_interpolated_across(pc, plant):  # noqa: F811
    url = f"{DATA}/signals/plant:FI-1.PV/series"
    params = {"start": START, "end": END, "step": 600, "sampling": "interpolated"}
    loose = pc.get(url, params=params).json()["v"]
    tight = pc.get(url, params={**params, "max_gap": 1200}).json()["v"]
    assert loose[2] == 60.0 and tight[2] is None  # 00:20, inside the 40-minute gap
    assert tight[:2] == [0.0, 60.0] and tight[5] == 60.0  # the samples themselves stay


def test_a_step_signal_interpolates_as_steps_and_the_batch_reads_the_same(pc, plant):  # noqa: F811
    body = {
        "signals": ["plant:XV-1.POS", "plant:FI-1.PV", "plant:FIC-1.MODE"],
        "start": START,
        "end": END,
        "step": 900,
        "sampling": "interpolated",
    }
    answer = pc.post(f"{DATA}/series", json=body).json()
    by_id = {item["signal"]: item for item in answer["series"]}
    assert by_id["plant:XV-1.POS"]["v"] == [0.0, 0.0, 1.0, 1.0, 1.0]
    single = pc.get(
        f"{DATA}/signals/plant:FI-1.PV/series",
        params={"start": START, "end": END, "step": 900, "sampling": "interpolated"},
    ).json()
    assert by_id["plant:FI-1.PV"]["v"] == single["v"]
    # Only numbers interpolate: the text signal fails alone.
    (error,) = answer["errors"]
    assert error["signal"] == "plant:FIC-1.MODE" and error["status"] == 422


def test_bad_sampling_options_are_refused(pc, plant):  # noqa: F811
    url = f"{DATA}/signals/plant:FI-1.PV/series"
    base = {"start": START, "end": END}
    for params in (
        {"sampling": "interpolated"},  # no step
        {"step": 60, "sampling": "nearest"},
        {"step": 60, "max_gap": 60},  # max_gap without interpolated
        {"step": 60, "sampling": "interpolated", "max_gap": -1},
    ):
        assert pc.get(url, params={**base, **params}).status_code == 422, params


def test_the_summary_counts_covers_totals_and_says_how_much_was_good(pc, plant):  # noqa: F811
    answer = pc.get(
        f"{DATA}/signals/plant:FI-1.PV/summary", params={"start": START, "end": END}
    ).json()
    assert answer["signal"] == "plant:FI-1.PV" and answer["unit"] == "t/h"
    assert answer["count"] == 3 and answer["per"] == "h"
    # The signal has a value from 00:00 to 00:50: 50 of 60 minutes.
    assert answer["covered_pct"] == pytest.approx(100 * 50 / 60, abs=1e-3)
    # 0 to 60 t/h over 10 minutes (5 t), then 60 t/h for 40 minutes (40 t).
    assert answer["total"] == pytest.approx(45.0)
    assert answer["mean"] == pytest.approx(54.0) and answer["max"] == 60.0
    # Uncertain for 15 of 60 minutes.
    assert answer["good_pct"] == pytest.approx(75.0)
    per_minute = pc.get(
        f"{DATA}/signals/plant:FI-1.PV/summary", params={"start": START, "end": END, "per": "min"}
    ).json()
    assert per_minute["total"] == pytest.approx(45.0 * 60)
    text = pc.get(
        f"{DATA}/signals/plant:FIC-1.MODE/summary", params={"start": START, "end": END}
    ).json()
    assert text["count"] == 1 and text["total"] is None and text["good_pct"] == 100.0
    assert (
        pc.get(
            f"{DATA}/signals/plant:FI-1.PV/summary", params={"start": START, "per": "week"}
        ).status_code
        == 422
    )


def test_interpolation_edges():
    times = np.array([0, 1000, 2000, 5000], dtype=np.int64)
    values = np.array([0.0, 10.0, np.nan, 7.0])
    grid = np.array([-500, 0, 500, 1000, 1500, 3000, 5000, 6000], dtype=float)
    out = _interpolate(times, values, False, grid, None)
    # Before the first sample, across the gap marker and past the last: NaN.
    assert np.isnan(out[0]) and np.isnan(out[4]) and np.isnan(out[5]) and np.isnan(out[7])
    assert list(out[[1, 2, 3, 6]]) == [0.0, 5.0, 10.0, 7.0]
    held = _interpolate(times, values, True, grid, 1500)
    # Held: the last sample, within max_gap past the last sample (6000 is 1000 after it).
    assert held[2] == 0.0 and np.isnan(held[5]) and held[6] == 7.0 and held[7] == 7.0
    assert np.isnan(_interpolate(times, values, True, np.array([7000.0]), 1500)[0])
