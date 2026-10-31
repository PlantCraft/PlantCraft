"""FakePlantCraft's value route on long windows (regression)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from plantcraft_sdk.testing import FakePlantCraft

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def test_value_over_long_windows_of_a_recorded_series():
    """Regression: 31d, 90d and 366d windows on recorded samples with and without
    fractional seconds or an offset raised ValueError in the fake."""

    stamps = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-01-01T00:00:00Z"),
            pd.Timestamp("2026-01-15T00:00:00.5Z"),
            pd.Timestamp("2026-01-20T03:00:00+03:00").tz_convert("UTC"),
            pd.Timestamp("2026-02-01T00:00:00Z"),
        ]
    )
    series = pd.Series([1.0, 2.0, 3.0, 4.0], index=stamps)
    client = FakePlantCraft(series={"fake:FIC-101.PV": series}).client("engineer")
    for window in ("31d", "90d", "366d"):
        assert client.value("fake:FIC-101.PV", "mean", window)["value"] == 2.5
        assert client.value("fake:FIC-101.PV", "last", window)["value"] == 4.0
    # Long windows of the synthetic signal are summarized on a grid of fractional steps.
    long = FakePlantCraft(now=NOW, sample_seconds=1).client("engineer")
    assert long.value("fake:FIC-101.PV", "mean", "366d")["value"] is not None
    assert NOW - timedelta(days=1) < datetime.fromisoformat(long.value("fake:FIC-101.PV")["at"])


def test_value_over_a_window_that_closed_earlier():
    """``end`` reads a closed window (a report of last week), never past the newest data."""

    stamps = pd.date_range("2026-01-01", periods=4, freq="7D", tz="UTC")
    series = pd.Series([1.0, 2.0, 3.0, 4.0], index=stamps)
    client = FakePlantCraft(series={"fake:FIC-101.PV": series}).client("engineer")
    closed = client.value(
        "fake:FIC-101.PV", "last", "8d", end=datetime(2026, 1, 9, tzinfo=timezone.utc)
    )
    assert closed["value"] == 2.0
    assert client.value("fake:FIC-101.PV", "last", "8d", end="2999-01-01T00:00:00Z")["value"] == 4.0
