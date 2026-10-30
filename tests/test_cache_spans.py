"""History cache spans: late samples, resolution and per-tag retention."""

from __future__ import annotations

import pandas as pd

from plantcraft.config import DataSourceConfig
from plantcraft.db import Database
from plantcraft.industrial_data.cache import CachedSource, HistoryCache

T0 = pd.Timestamp("2026-10-16 10:00:00")


class LaggingSource:
    """A historian whose samples become readable ``lag`` after their timestamp."""

    def __init__(self, lag: pd.Timedelta = pd.Timedelta(0)):
        self.failed_tags = []
        self.calls = []
        self.now = T0
        self.lag = lag

    def read_range(self, start, end, sample_seconds, *, tags=None, include_boundary=True):
        self.calls.append((pd.Timestamp(start), pd.Timestamp(end), sample_seconds))
        visible = min(pd.Timestamp(end), self.now - self.lag)
        index = pd.date_range(
            pd.Timestamp(start).ceil(f"{sample_seconds}s"), visible, freq=f"{sample_seconds}s"
        )
        return pd.DataFrame(
            {tag: [float(i) for i in range(len(index))] for tag in tags}, index=index
        )


def make(tmp_path, source, kind="opcua", hours=72):
    if kind == "pi_web_api":
        config = DataSourceConfig(
            type=kind,
            server="PI",
            base_url="https://pi.example.test/piwebapi",
            tags=["A"],
            history_cache_hours=hours,
        )
    else:
        config = DataSourceConfig(
            type=kind, endpoint_url="opc.tcp://x", tags=["A"], history_cache_hours=hours
        )
    return CachedSource(source, HistoryCache(Database(tmp_path / "c.sqlite3")), config)


def test_samples_that_arrive_late_are_fetched_by_the_next_read(tmp_path):
    source = LaggingSource(lag=pd.Timedelta(minutes=2))
    cached = make(tmp_path, source)
    for step in range(4):
        source.now = T0 + pd.Timedelta(minutes=10 * step)
        cached.read_range(source.now - pd.Timedelta(minutes=60), source.now, 60, tags=["A"])
    source.now = T0 + pd.Timedelta(hours=2)
    frame = cached.read_range(
        T0 - pd.Timedelta(minutes=10), T0 + pd.Timedelta(minutes=35), 60, tags=["A"]
    )
    expected = pd.date_range(
        T0 - pd.Timedelta(minutes=10), T0 + pd.Timedelta(minutes=35), freq="60s"
    )
    assert expected.difference(frame.index).empty


def test_a_coarse_span_does_not_answer_a_finer_read_from_an_interpolating_source(tmp_path):
    source = LaggingSource()
    cached = make(tmp_path, source, kind="pi_web_api")
    cached.read_range(T0 - pd.Timedelta(hours=24), T0, 300, tags=["A"])
    frame = cached.read_range(T0 - pd.Timedelta(hours=1), T0, 60, tags=["A"])
    assert source.calls[-1][2] == 60
    assert len(frame) == 61
    # The finer span answers a coarser read, and extends at its own resolution.
    calls = len(source.calls)
    cached.read_range(T0 - pd.Timedelta(minutes=30), T0, 300, tags=["A"])
    assert len(source.calls) == calls
    source.now = T0 + pd.Timedelta(minutes=10)
    cached.read_range(T0 - pd.Timedelta(minutes=30), source.now, 300, tags=["A"])
    assert source.calls[-1][2] == 60


def test_raw_sources_ignore_the_resolution(tmp_path):
    source = LaggingSource()
    cached = make(tmp_path, source)
    cached.read_range(T0 - pd.Timedelta(hours=2), T0, 300, tags=["A"])
    cached.read_range(T0 - pd.Timedelta(hours=1), T0, 60, tags=["A"])
    assert len(source.calls) == 1


def test_retention_deletes_only_the_written_tags(tmp_path):
    source = LaggingSource()
    cached = make(tmp_path, source, hours=1)
    source.now = T0
    cached.read_range(T0 - pd.Timedelta(hours=3), T0, 60, tags=["A"])
    with cached.cache.db.connect() as connection:
        connection.execute(
            "INSERT INTO signal_samples VALUES (?, 'B', '2000-01-01T00:00:00.000000', 1.0)",
            (cached.key,),
        )
    source.now = T0 + pd.Timedelta(hours=1)
    cached.read_range(T0, source.now, 60, tags=["A"])
    with cached.cache.db.connect() as connection:
        oldest = connection.execute(
            "SELECT MIN(ts) FROM signal_samples WHERE tag = 'A'"
        ).fetchone()[0]
        other = connection.execute(
            "SELECT COUNT(*) FROM signal_samples WHERE tag = 'B'"
        ).fetchone()[0]
    assert pd.Timestamp(oldest) >= T0 - pd.Timedelta(hours=1)
    # Tag B was not written, so its rows were not scanned.
    assert other == 1
