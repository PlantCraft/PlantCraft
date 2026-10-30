"""The history cache serves repeated reads locally and fetches only new data."""

from __future__ import annotations

import pandas as pd

from plantcraft.config import DataSourceConfig
from plantcraft.db import Database
from plantcraft.industrial_data.cache import LATE_SAMPLES, CachedSource, HistoryCache

START = pd.Timestamp("2026-10-01 00:00:00")


class FakeSource:
    def __init__(self):
        self.failed_tags = []
        self.calls = []

    def read_range(self, start, end, sample_seconds, *, tags=None, include_boundary=True):
        self.calls.append((pd.Timestamp(start), pd.Timestamp(end), tuple(tags)))
        index = pd.date_range(pd.Timestamp(start).ceil("30s"), end, freq="30s")
        data = {tag: [float(i) for i in range(len(index))] for tag in tags if tag != "MODE"}
        if "MODE" in tags:
            data["MODE"] = ["AUTO"] * len(index)
        return pd.DataFrame(data, index=index)


def make(tmp_path, hours=72):
    config = DataSourceConfig(
        type="opcua",
        endpoint_url="opc.tcp://localhost:4840",
        tags=["A.PV", "A.SP", "MODE"],
        history_cache_hours=hours,
    )
    fake = FakeSource()
    return fake, CachedSource(fake, HistoryCache(Database(tmp_path / "c.sqlite3")), config)


def test_second_read_is_served_from_cache(tmp_path):
    fake, cached = make(tmp_path)
    end = START + pd.Timedelta(hours=48)
    first = cached.read_range(START, end, 30)
    second = cached.read_range(START, end, 30)
    assert len(fake.calls) == 1
    assert cached.last_read_from_cache
    pd.testing.assert_frame_equal(first, second, check_freq=False)
    assert len(first) == 48 * 120 + 1
    assert set(first["MODE"]) == {"AUTO"}


def test_extending_the_window_fetches_only_the_tail(tmp_path):
    fake, cached = make(tmp_path)
    cached.read_range(START, START + pd.Timedelta(hours=1), 30)
    cached.read_range(START + pd.Timedelta(minutes=30), START + pd.Timedelta(hours=2), 30)
    assert len(fake.calls) == 2
    tail_start, tail_end, _ = fake.calls[1]
    # The tail overlaps the cached end a little, for samples that arrive late.
    assert tail_start == START + pd.Timedelta(hours=1) - LATE_SAMPLES
    assert tail_end == START + pd.Timedelta(hours=2)


def test_reading_before_the_cached_span_refetches(tmp_path):
    fake, cached = make(tmp_path)
    cached.read_range(START + pd.Timedelta(hours=1), START + pd.Timedelta(hours=2), 30)
    cached.read_range(START, START + pd.Timedelta(hours=2), 30)
    assert fake.calls[1][0] == START


def test_retention_drops_old_samples(tmp_path):
    fake, cached = make(tmp_path, hours=1)
    cached.read_range(START, START + pd.Timedelta(hours=3), 30, tags=["A.PV"])
    with cached.cache.db.connect() as connection:
        oldest = connection.execute("SELECT MIN(ts) FROM signal_samples").fetchone()[0]
    assert pd.Timestamp(oldest) >= START + pd.Timedelta(hours=2)
