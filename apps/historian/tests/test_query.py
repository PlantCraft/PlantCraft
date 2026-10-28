from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.contract import ContractError

from histcraft.archive.query import PointRef, Reader, to_ms
from histcraft.archive.store import ArchiveStore
from tests.conftest import database

T0 = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
MS = to_ms(T0)
NUMBER = PointRef(1, "TI-100.PV")
STEP = PointRef(2, "XV-102.OPEN", step=True)
TEXT = PointRef(3, "FIC-101.MODE", kind="text")


@pytest.fixture
def reader(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    # A ramp 0 -> 100 over 100 s, flat 100 to 200 s, then a gap, then 50 from 300 s to 400 s.
    archive.append(
        {
            1: (
                "number",
                [
                    (MS, 0.0),
                    (MS + 100_000, 100.0),
                    (MS + 200_000, 100.0),
                    (MS + 250_000, float("nan")),
                    (MS + 300_000, 50.0),
                ],
            ),
            2: ("number", [(MS, 0.0), (MS + 10_000, 1.0), (MS + 20_000, 0.0)]),
            3: ("text", [(MS, "AUTO"), (MS + 60_000, "MAN"), (MS + 120_000, None)]),
        }
    )
    archive.put_snapshots([{"point": 1, "ts": MS + 400_000, "value": 50.0, "status": "ok"}])
    return Reader(archive)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def test_recorded_values_include_the_snapshot_and_skip_gap_markers(reader):
    stamps, values = reader.series(NUMBER, at(0), at(500), None)
    assert values == [0.0, 100.0, 100.0, 50.0, 50.0]
    assert stamps[-1] == "2026-10-19T00:06:40+00:00"


def test_averages_are_time_weighted_over_the_rebuilt_line(reader):
    _, values = reader.series(NUMBER, at(0), at(500), 50)
    assert values[:4] == [25.0, 75.0, 100.0, 100.0]
    # 250-300 s and 200-250 s: no line across the gap marker
    assert values[4] is None and values[5] is None
    assert values[6:8] == [50.0, 50.0]
    # after the snapshot nothing is known
    assert values[8] is None and values[9] is None


def test_averages_match_pandas_on_dense_data(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    rng = np.random.default_rng(3)
    values = rng.normal(10, 2, 3601)
    archive.append({1: ("number", [(MS + i * 1000, float(v)) for i, v in enumerate(values)])})
    _, got = Reader(archive).series(NUMBER, at(0), at(3600), 60)
    # Trapezoids per minute, as pandas would integrate the same line.
    expected = [np.trapezoid(values[m * 60 : m * 60 + 61], dx=1) / 60 for m in range(60)]
    assert np.allclose(got, expected)


def test_step_points_hold_their_value(reader):
    _, values = reader.series(STEP, at(0), at(20), 5)
    assert values == [0.0, 0.0, 1.0, 1.0]


def test_text_grid_gives_the_label_in_effect_at_the_end(reader):
    _, labels = reader.series(TEXT, at(0), at(180), 30)
    assert labels == ["AUTO", "AUTO", "MAN", "MAN", None, None]
    _, recorded = reader.series(TEXT, at(0), at(180), None)
    assert recorded == ["AUTO", "MAN"]


def test_value_aggregations(reader):
    now = at(100)
    assert reader.value(NUMBER, "mean", "100s", now)["value"] == pytest.approx(50.0)
    assert reader.value(NUMBER, "min", "100s", now)["value"] == 0.0
    assert reader.value(NUMBER, "max", "50s", now)["value"] == 100.0
    std = reader.value(NUMBER, "std", "100s", now)["value"]
    assert std == pytest.approx(100 / np.sqrt(12), rel=1e-6)
    last = reader.value(NUMBER, "last", "1h", at(450))
    assert last["value"] == 50.0 and last["at"] == "2026-10-19T00:06:40+00:00"
    assert reader.value(TEXT, "last", "1h", at(100))["value"] == "MAN"


def test_last_inside_a_gap_is_unknown(reader):
    assert reader.value(NUMBER, "last", "60s", at(280))["value"] is None


def test_bad_requests_are_contract_errors(reader):
    with pytest.raises(ContractError):
        reader.value(TEXT, "mean", "1h")
    with pytest.raises(ContractError):
        reader.value(NUMBER, "median", "1h")
    with pytest.raises(ContractError):
        reader.value(NUMBER, "last", "forever")
    with pytest.raises(ContractError):
        reader.series(NUMBER, at(0), at(10**6), 1)


def test_unknown_point_reads_empty(reader):
    stamps, values = reader.series(PointRef(99, "x"), at(0), at(60), 10)
    assert len(stamps) == 6 and values == [None] * 6
    assert reader.value(PointRef(99, "x"), "mean", "1h")["value"] is None
    assert pd.Timestamp(stamps[0]) == pd.Timestamp(at(0))


@pytest.fixture
def on_change(tmp_path):
    """A setpoint written every 30 s for a minute and then left alone, its mode, a PV with the
    same samples, and a setpoint whose last sample is a "no data" marker."""

    archive = ArchiveStore(database(tmp_path))
    numbers = [(MS, 40.0), (MS + 30_000, 50.0), (MS + 60_000, 50.0)]
    archive.append(
        {
            11: ("number", numbers),
            12: ("text", [(MS, "AUTO"), (MS + 30_000, "CAS")]),
            13: ("number", numbers),
            14: ("number", [*numbers, (MS + 90_000, float("nan"))]),
        }
    )
    return Reader(archive)


SETPOINT = PointRef(11, "plantcraft:fic-101.sp")
MODE_TEXT = PointRef(12, "plantcraft:scenario:state", kind="text")
PV_LIKE = PointRef(13, "plantcraft:FIC-101.PV")
SETPOINT_NULL = PointRef(14, "plantcraft:FIC-102.Setpoint")


def test_signals_recorded_on_change_hold_to_now_on_a_grid(on_change):
    # Rebuilt as steps (40 for 30 s, then 50) and held long past ten spacings, any case.
    _, values = on_change.series(SETPOINT, at(0), at(1200), 60, now=at(1200))
    assert values == [45.0] + [50.0] * 19
    # Text signals hold too, whatever their tag.
    _, labels = on_change.series(MODE_TEXT, at(0), at(600), 60, now=at(600))
    assert labels == ["CAS"] * 10
    # A sampled signal (PV) still ends at its last value: a silent source stays a gap.
    _, pv = on_change.series(PV_LIKE, at(0), at(600), 60, now=at(600))
    assert pv[0] is not None and pv[1:] == [None] * 9
    # Recorded values are unchanged: no invented sample.
    _, recorded = on_change.series(SETPOINT, at(0), at(600), None, now=at(600))
    assert recorded == [40.0, 50.0, 50.0]


def test_the_on_change_hold_stops_at_now_and_at_a_null_sample(on_change):
    # Nothing is held into the future: the step that holds now is the last one with a value.
    _, values = on_change.series(SETPOINT, at(0), at(600), 60, now=at(330))
    assert values[:6] == [45.0, 50.0, 50.0, 50.0, 50.0, 50.0] and values[6:] == [None] * 4
    _, labels = on_change.series(MODE_TEXT, at(0), at(600), 60, now=at(330))
    assert labels[:6] == ["CAS"] * 6 and labels[6:] == [None] * 4
    # A "no data" marker ends the hold.
    _, ended = on_change.series(SETPOINT_NULL, at(0), at(600), 60, now=at(600))
    assert ended[0] == 45.0 and ended[1] == 50.0 and ended[2:] == [None] * 8


def test_a_text_snapshot_in_a_number_point_is_a_gap_not_a_failure(tmp_path):
    # A MODE archived as a number before its kind was known: the read still answers.
    archive = ArchiveStore(database(tmp_path))
    archive.append({1: ("number", [(MS, 1.0)])})
    archive.put_snapshots([{"point": 1, "ts": MS + 60_000, "value": "AUTO", "status": "ok"}])
    stamps, values = Reader(archive).series(NUMBER, at(0), at(120), None)
    assert values[0] == 1.0 and len(stamps) == len(values)
