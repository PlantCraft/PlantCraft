"""Regular grids hold the last value into empty steps (docs/api-v1.md, "Series").

A setpoint or a mode recorded on change, or a signal scanned slower than the step, keeps
its value between samples, as a historian's step-hold does; nothing is filled before the
first sample, after ``now``, past a null sample, or across a silence longer than the hold
limit (``HOLD_STEPS`` times the larger of the step and the signal's usual spacing).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from plantcraft_sdk.contract import (
    HOLD_STEPS,
    hold_limit,
    recorded_on_change,
    shape_series,
    shape_text_series,
    shape_values,
)
from plantcraft_sdk.testing import FakePlantCraft

START = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


def _at(minutes: list[float], values: list) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex([START + m * MINUTE for m in minutes]))


def test_a_setpoint_recorded_on_change_is_held_across_steps():
    sp = _at([2, 7, 23], [50.0, 55.0, 60.0])
    _, v = shape_series(sp, START, START + 30 * MINUTE, 300, now=NOW)
    # Steps of 5 min: [0,5) has 50, [5,10) has 55, then held until 60 at minute 23.
    assert v == [50.0, 55.0, 55.0, 55.0, 60.0, 60.0]


def test_a_step_with_samples_keeps_their_mean():
    pv = _at([0, 1, 2, 9], [1.0, 2.0, 6.0, 4.0])
    _, v = shape_series(pv, START, START + 15 * MINUTE, 300, now=NOW)
    assert v == [3.0, 4.0, 4.0]


def test_an_empty_trailing_step_holds_the_last_value():
    pv = _at(list(range(0, 58, 3)), [float(m) for m in range(0, 58, 3)])  # every 3 min
    t, v = shape_series(pv, START, START + 60 * MINUTE, 60, now=NOW)
    assert len(t) == 60 and v[-1] == 57.0 and None not in v
    assert v[1] == 0.0 and v[2] == 0.0 and v[3] == 3.0  # held between samples


def test_a_text_mode_holds_its_last_label():
    mode = _at([14, 26], ["AUTO", "MAN"])
    _, v = shape_text_series(mode, START, START + 40 * MINUTE, 600, now=NOW)
    assert v == [None, "AUTO", "MAN", "MAN"]
    _, same = shape_values(mode, START, START + 40 * MINUTE, 600, "text", now=NOW)
    assert same == v


def test_nothing_is_filled_before_the_first_sample():
    pv = _at([31, 32, 33], [7.0, 8.0, 9.0])
    _, v = shape_series(pv, START, START + 60 * MINUTE, 600, now=NOW)
    assert v == [None, None, None, 8.0, 9.0, 9.0]
    _, labels = shape_text_series(_at([31], ["MAN"]), START, START + 60 * MINUTE, 600, now=NOW)
    assert labels == [None, None, None, "MAN", "MAN", "MAN"]


def test_a_look_back_sample_before_start_seeds_the_hold():
    sp = _at([-90, 12], [40.0, 45.0])  # the reader's last value before start
    _, v = shape_series(sp, START, START + 20 * MINUTE, 300, now=NOW)
    assert v == [40.0, 40.0, 45.0, 45.0]
    recorded, values = shape_series(sp, START, START + 20 * MINUTE, None)
    assert values == [45.0] and len(recorded) == 1  # recorded values stay inside the range


def test_a_long_outage_is_not_filled():
    # A PV every 10 s, then a two-hour silence: held 10 steps (10 min at a 60 s step), no more.
    seconds = np.arange(0, 1800, 10)
    before = pd.Series(
        seconds.astype(float),
        index=pd.DatetimeIndex([START + timedelta(seconds=int(s)) for s in seconds]),
    )
    after = _at([150, 151, 152], [1.0, 2.0, 3.0])
    pv = pd.concat([before, after])
    assert hold_limit(pv.index, 60) == HOLD_STEPS * 60
    _, v = shape_series(pv, START, START + 160 * MINUTE, 60, now=NOW)
    last = 1790.0
    assert v[29] == np.mean(seconds[-6:]) and v[30:40] == [last] * 10
    assert v[40:150] == [None] * 110  # the outage stays a gap
    assert v[150:153] == [1.0, 2.0, 3.0] and v[153:] == [3.0] * 7


def test_a_null_sample_ends_the_hold():
    sp = _at([1, 3, 6, 21], [10.0, 20.0, np.nan, 30.0])  # the source said "no value" at 6
    _, v = shape_series(sp, START, START + 25 * MINUTE, 300, now=NOW)
    assert v == [15.0, None, None, None, 30.0]
    _, labels = shape_text_series(
        _at([1, 6, 21], ["AUTO", "", "MAN"]), START, START + 25 * MINUTE, 300, now=NOW
    )
    assert labels == ["AUTO", None, None, None, "MAN"]


def test_nothing_is_held_into_the_future():
    sp = _at([0], [5.0])
    _, v = shape_series(sp, START, START + 30 * MINUTE, 600, now=START + 12 * MINUTE)
    assert v == [5.0, 5.0, None]


def test_the_fake_answers_the_held_grid():
    sp = _at([2, 7, 23], [50.0, 55.0, 60.0])
    fake = FakePlantCraft(series={"fake:FIC-101.SP": sp}, now=NOW)
    client = fake.client("engineer")
    answer = client.series("fake:FIC-101.SP", START, START + 30 * MINUTE, step=300)
    assert answer["v"] == [50.0, 55.0, 55.0, 55.0, 60.0, 60.0]


def _every(seconds: int, until_minutes: int, value: float) -> pd.Series:
    stamps = [START + timedelta(seconds=s) for s in range(0, until_minutes * 60, seconds)]
    return pd.Series([value] * len(stamps), index=pd.DatetimeIndex(stamps))


def test_a_setpoint_recorded_on_change_holds_up_to_now():
    # Written every 30 s for an hour (a demo's pre-written history), then only on change:
    # nothing for the next hour. Its spacing (30 s) says nothing about the source, so the
    # last value holds to now, not ten steps.
    sp = _every(30, 60, 55.0)
    _, v = shape_series(
        sp, START, START + 120 * MINUTE, 60, now=START + 115 * MINUTE, on_change=True
    )
    assert v[:116] == [55.0] * 116 and v[116:] == [None] * 4  # never past now
    _, held = shape_values(sp, START, START + 120 * MINUTE, 60, now=NOW, signal_id="s:FIC-1.SP")
    assert held == [55.0] * 120
    # The same samples on a sampled signal (a PV) are an outage after ten steps.
    _, pv = shape_values(sp, START, START + 120 * MINUTE, 60, now=NOW, signal_id="s:FIC-1.PV")
    assert pv[:70] == [55.0] * 70 and pv[70:] == [None] * 50


def test_a_null_sample_still_ends_the_hold_of_a_setpoint():
    sp = pd.concat([_every(30, 10, 40.0), _at([10], [np.nan])])
    _, v = shape_values(sp, START, START + 30 * MINUTE, 60, now=NOW, signal_id="FIC-1.SP")
    assert v[:10] == [40.0] * 10 and v[10:] == [None] * 20


def test_a_text_mode_holds_up_to_now():
    stamps = [START + timedelta(seconds=s) for s in range(0, 3600, 30)]
    mode = pd.Series(["AUTO"] * len(stamps), index=pd.DatetimeIndex(stamps))
    _, v = shape_values(mode, START, START + 120 * MINUTE, 60, "text", now=NOW)
    assert v == ["AUTO"] * 120


def test_which_signals_are_recorded_on_change():
    for signal_id in ("FIC-101.SP", "scenario:sp", "pi:Unit 2\\FIC 101.SP", "a:TK_1/Mode"):
        assert recorded_on_change(signal_id)
    for signal_id in ("FIC-101.PV", "scenario:op", "app-linkcraft:FIC-1.PV.quality", "", "SPAN"):
        assert not recorded_on_change(signal_id)
    assert recorded_on_change("FIC-101.STATE", "text")


def test_the_fake_holds_a_setpoint_up_to_now():
    sp = _every(30, 60, 55.0)
    fake = FakePlantCraft(series={"fake:FIC-101.SP": sp}, now=NOW)
    client = fake.client("engineer")
    answer = client.series("fake:FIC-101.SP", START, START + 120 * MINUTE, step=60)
    assert answer["v"] == [55.0] * 120
