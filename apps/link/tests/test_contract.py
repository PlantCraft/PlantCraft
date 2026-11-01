"""Analytics reads plant data only through API v1; the adapter's side of that contract."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest
from plantcraft_sdk.client import Unavailable

from linkcraft.data.frames import build_loop_frame
from linkcraft.data.plant import PlantData, mode_text
from tests.plant import NOW, SAMPLE_SECONDS, PlantFake, make_fake, sid

START = NOW - timedelta(hours=1)


@pytest.fixture
def plant():
    return PlantData(make_fake().client("engineer"))


def test_recorded_series_become_one_naive_utc_column_per_signal(plant):
    frame = plant.read_range(
        START, NOW, SAMPLE_SECONDS, tags=[sid("FIC-101.PV"), sid("FIC-101.SP")]
    )
    assert list(frame.columns) == [sid("FIC-101.PV"), sid("FIC-101.SP")]
    assert frame.index.tz is None
    assert frame.index.max() == pd.Timestamp(NOW).tz_convert(None)
    assert len(frame) == 361  # one hour of 10 s samples, both ends included
    assert frame.attrs["failed_tags"] == []


def test_unknown_signals_are_listed_not_fatal(plant):
    frame = plant.read_range(START, NOW, SAMPLE_SECONDS, tags=[sid("FIC-101.PV"), "NOPE"])
    assert list(frame.columns) == [sid("FIC-101.PV")]
    assert [tag for tag, _ in frame.attrs["failed_tags"]] == ["NOPE"]


def test_a_mode_signal_reaches_the_methods_as_text(plant):
    frame = plant.read_range(
        START, NOW, SAMPLE_SECONDS, tags=[sid("FIC-101.MODE")], text_signals={sid("FIC-101.MODE")}
    )
    assert set(frame[sid("FIC-101.MODE")].dropna()) == {"1"}
    labels = mode_text(pd.Series([0.0, 2.5, None])).tolist()
    assert labels[:2] == ["0", "2.5"] and pd.isna(labels[2])


def test_too_many_points_fall_back_to_one_mean_per_step():
    """24 days of 10 s samples break the 200,000-point limit: that signal comes as means."""

    fake = PlantFake(now=NOW)
    client = fake.client("engineer")
    fake.requests = 0
    frame = PlantData(client).read_range(
        NOW - timedelta(days=24), NOW, 600, tags=[sid("FIC-101.PV"), sid("FIC-101.SP")]
    )
    assert list(frame.columns) == [sid("FIC-101.PV"), sid("FIC-101.SP")]
    assert len(frame) == 24 * 144 and frame.attrs["failed_tags"] == []
    assert fake.requests == 2  # the batch, then one batch of means for the crowded signals


def test_all_signals_read_in_one_request(plant):
    fake = make_fake()
    fake.requests = 0
    tags = [
        sid("FIC-101.PV"),
        sid("FIC-101.SP"),
        sid("FIC-101.OP"),
        sid("LIC-102.PV"),
        sid("LIC-102.SP"),
    ]
    frame = PlantData(fake.client("engineer")).read_range(START, NOW, SAMPLE_SECONDS, tags=tags)
    assert list(frame.columns) == tags and fake.requests == 1


def test_many_signals_are_split_over_parallel_requests():
    signals = [
        {
            "id": f"T{n}",
            "name": "",
            "source": "fake",
            "unit": "",
            "description": "",
            "low": None,
            "high": None,
        }
        for n in range(200)
    ]
    fake = PlantFake(signals=signals, now=NOW)
    fake.requests = 0
    tags = [item["id"] for item in signals]
    frame = PlantData(fake.client("engineer"), threads=4).read_range(
        NOW - timedelta(minutes=10), NOW, 10, tags=tags
    )
    assert list(frame.columns) == tags and fake.requests == 4


def test_processcraft_down_fails_the_batch():
    fake = make_fake()
    fake.broken.update({sid("FIC-101.PV"): "restarting", sid("LIC-102.PV"): "restarting"})
    with pytest.raises(Unavailable):
        PlantData(fake.client("engineer")).read_range(
            START, NOW, 10, tags=[sid("FIC-101.PV"), sid("LIC-102.PV")]
        )


def test_one_dead_signal_is_listed_and_the_rest_read():
    fake = make_fake()
    fake.broken[sid("LIC-102.PV")] = "tag offline"
    frame = PlantData(fake.client("engineer")).read_range(
        START, NOW, 10, tags=[sid("FIC-101.PV"), sid("LIC-102.PV")]
    )
    assert list(frame.columns) == [sid("FIC-101.PV")]
    ((tag, reason),) = frame.attrs["failed_tags"]
    assert tag == sid("LIC-102.PV") and "502" in reason and "tag offline" in reason


def test_text_mode_labels_reach_the_frame_as_labels():
    labels = pd.Series(
        ["AUTO", "MAN", "AUTO"],
        index=pd.to_datetime([START, START + timedelta(minutes=20), START + timedelta(minutes=40)]),
    )
    fake = make_fake()
    fake.series_data[sid("FIC-101.MODE")] = labels
    frame = PlantData(fake.client("engineer")).read_range(
        START, NOW, SAMPLE_SECONDS, tags=[sid("FIC-101.PV"), sid("FIC-101.MODE")]
    )
    assert frame[sid("FIC-101.MODE")].dropna().tolist() == ["AUTO", "MAN", "AUTO"]


def test_the_round_ends_at_the_newest_sample(plant):
    end = plant.data_end([sid("FIC-101.PV"), sid("LIC-102.PV")], 360)
    assert end == pd.Timestamp(NOW).tz_convert(None)


def test_series_are_resampled_onto_the_loop_grid(plant, analysed):
    loop = analysed.loops.get_loop("lic-102")
    raw = plant.read_range(START, NOW, SAMPLE_SECONDS, tags=[sid("LIC-102.PV"), sid("LIC-102.SP")])
    frame = build_loop_frame(raw, loop, 30)
    assert {"timestamp", "pv", "sp"} <= set(frame.columns)
    assert frame["timestamp"].diff().dropna().dt.total_seconds().eq(30).all()


def test_asset_types_are_optional_on_an_older_processcraft():
    """``GET /api/v1/asset-types`` is read when served; a 404 means "use PV and OP"."""

    from linkcraft.loops.sync import asset_types

    catalog = make_fake(catalog=True)
    served = asset_types(catalog.client("engineer"))
    cascade = next(item for item in served if item["id"] == "cascade_loop")
    assert cascade["path"] == ["loop", "cascade_loop"] and cascade["parent"] == "loop"
    assert [role["key"] for role in cascade["roles"]] == ["pv", "sp", "op", "mode", "secondary"]
    assert asset_types(make_fake(older=True).client("engineer")) is None


def test_a_time_given_twice_does_not_fail_the_batch(plant, monkeypatch):
    """A historian may answer the same time twice (overlapping chunks): the batch's other
    signals still come, and the repeated time keeps its last value."""

    times = pd.to_datetime(["2026-10-19T06:00:00Z", "2026-10-19T06:00:10Z"] * 2)
    twice = pd.Series([1.0, 2.0, 3.0, 4.0], index=times)
    once = pd.Series([5.0, 6.0], index=times[:2])
    monkeypatch.setattr(plant, "_read", lambda *args: ({"A": twice, "B": once}, []))
    frame = plant.read_range(START, NOW, SAMPLE_SECONDS, tags=["A", "B"])
    assert list(frame.columns) == ["A", "B"] and len(frame) == 2
    assert frame["A"].tolist() == [3.0, 4.0]
