"""Local cache of historical samples in front of a slow industrial source.

Each tag keeps one covered span. A read inside the span is served from SQLite;
a read that extends past its end fetches only the missing tail from the
source. A span ends at the last sample the source returned (late samples are
fetched by the next read) and remembers the resolution it was read at, so a
coarse read never answers a finer one. Samples older than the retention are
deleted per tag, at most every few minutes.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from processcraft.config import DataSourceConfig
from processcraft.db import Database, Migration, Store, add_columns
from processcraft.i18n import t
from processcraft.industrial_data.sources import DataSource, SignalInfo, build_source

_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"
# Samples can reach the historian late (buffered collectors): each tail read
# starts this much before the cached end, so late values are picked up.
LATE_SAMPLES = pd.Timedelta(minutes=15)
# Old samples of a tag are deleted at most this often.
PRUNE_SECONDS = 600
# Only interpolating sources answer differently per resolution; raw sources
# return every sample whatever is asked, so their spans fit any read.
RESAMPLING_SOURCES = {"pi_web_api"}


def source_key(config: DataSourceConfig) -> str:
    identity = (
        f"{config.type}|{config.endpoint_url}|{config.base_url}|{config.server}|{config.path}"
    )
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def _ts(value: pd.Timestamp | datetime) -> str:
    return pd.Timestamp(value).strftime(_TS_FORMAT)


class HistoryCache(Store):
    """Samples per (source, tag) and the interval each tag has cached."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS signal_samples (
        source_key TEXT NOT NULL,
        tag TEXT NOT NULL,
        ts TEXT NOT NULL,
        value,
        PRIMARY KEY(source_key, tag, ts)
    ) WITHOUT ROWID;

    CREATE TABLE IF NOT EXISTS signal_spans (
        source_key TEXT NOT NULL,
        tag TEXT NOT NULL,
        span_start TEXT NOT NULL,
        span_end TEXT NOT NULL,
        sample_seconds INTEGER,
        PRIMARY KEY(source_key, tag)
    );
    """

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "signal_spans",
                {
                    # Spans cached before this column fit any read, as they did then.
                    "sample_seconds": "INTEGER",
                },
            ),
        ),
    )

    def __init__(self, db: Database):
        super().__init__(db)
        self._pruned: dict[tuple[str, str], float] = {}

    def clear(self, key: str) -> None:
        """Forget everything cached for one source (for example after a simulator reset)."""

        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM signal_samples WHERE source_key = ?", (key,))
            connection.execute("DELETE FROM signal_spans WHERE source_key = ?", (key,))

    def spans(self, key: str, tags: list[str]) -> dict[str, tuple[pd.Timestamp, pd.Timestamp, int]]:
        """Each tag's cached ``(start, end, sample_seconds)``; 0 seconds fits any read."""

        if not tags:
            return {}
        placeholders = ",".join("?" for _ in tags)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT tag, span_start, span_end, sample_seconds FROM signal_spans
                WHERE source_key = ? AND tag IN ({placeholders})
                """,
                (key, *tags),
            ).fetchall()
        return {
            row["tag"]: (
                pd.Timestamp(row["span_start"]),
                pd.Timestamp(row["span_end"]),
                int(row["sample_seconds"] or 0),
            )
            for row in rows
        }

    def store(
        self,
        key: str,
        samples: dict[str, pd.Series],
        spans: dict[str, tuple[pd.Timestamp, pd.Timestamp, int]],
        cutoff: pd.Timestamp | None,
    ) -> None:
        rows = []
        for tag, series in samples.items():
            values = series.dropna()
            rows.extend(
                (key, tag, _ts(stamp), value.item() if hasattr(value, "item") else value)
                for stamp, value in values.items()
            )
        stale: list[str] = []
        if cutoff is not None:
            # Per tag (the primary key's prefix) instead of the whole source, and
            # not on every write: this runs under the database lock.
            now = time.monotonic()
            for tag in samples:
                if now - self._pruned.get((key, tag), float("-inf")) >= PRUNE_SECONDS:
                    self._pruned[(key, tag)] = now
                    stale.append(tag)
        with self._lock, self._write() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO signal_samples VALUES (?, ?, ?, ?)",
                rows,
            )
            for tag, (start, end, seconds) in spans.items():
                connection.execute(
                    """
                    INSERT INTO signal_spans VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_key, tag) DO UPDATE SET
                        span_start = excluded.span_start,
                        span_end = excluded.span_end,
                        sample_seconds = excluded.sample_seconds
                    """,
                    (key, tag, _ts(start), _ts(end), seconds),
                )
            for tag in stale:
                connection.execute(
                    "DELETE FROM signal_samples WHERE source_key = ? AND tag = ? AND ts < ?",
                    (key, tag, _ts(cutoff)),
                )
                connection.execute(
                    """
                    UPDATE signal_spans SET span_start = ?
                    WHERE source_key = ? AND tag = ? AND span_start < ?
                    """,
                    (_ts(cutoff), key, tag, _ts(cutoff)),
                )

    def load(
        self,
        key: str,
        tags: list[str],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        """Wide frame of cached samples, with each tag's last earlier value at ``start``."""

        series: dict[str, pd.Series] = {}
        with self._lock, self._connect() as connection:
            for tag in tags:
                rows = connection.execute(
                    """
                    SELECT ts, value FROM (
                        SELECT ts, value FROM signal_samples
                        WHERE source_key = ? AND tag = ? AND ts < ?
                        ORDER BY ts DESC LIMIT 1
                    )
                    UNION ALL
                    SELECT ts, value FROM signal_samples
                    WHERE source_key = ? AND tag = ? AND ts >= ? AND ts <= ?
                    ORDER BY ts
                    """,
                    (key, tag, _ts(start), key, tag, _ts(start), _ts(end)),
                ).fetchall()
                if not rows:
                    continue
                index = pd.to_datetime([row["ts"] for row in rows])
                values = pd.Series([row["value"] for row in rows], index=index, name=tag)
                if index[0] < start:
                    boundary = values.iloc[0]
                    values = values.iloc[1:]
                    if start not in values.index:
                        values = pd.concat([pd.Series([boundary], index=[start]), values])
                series[tag] = values
        if not series:
            return pd.DataFrame()
        frame = pd.concat(series.values(), axis=1, keys=series.keys()).sort_index()
        return frame.loc[~frame.index.duplicated(keep="last")]


class CachedSource:
    """A ``DataSource`` that reads through a ``HistoryCache``."""

    def __init__(
        self,
        source: DataSource,
        cache: HistoryCache,
        config: DataSourceConfig,
    ):
        self.source = source
        self.cache = cache
        self.config = config
        self.key = source_key(config)
        self.retention = timedelta(hours=config.history_cache_hours)
        self._lock = threading.Lock()
        self.last_read_from_cache = False

    @property
    def failed_tags(self) -> list[tuple[str, str]]:
        return self.source.failed_tags

    def list_signals(self) -> list[SignalInfo]:
        return self.source.list_signals()

    def test_connection(self) -> str | None:
        return self.source.test_connection()

    def read_window(self, minutes: int, sample_seconds: int) -> pd.DataFrame:
        end = pd.Timestamp.now(tz=self.config.timezone).tz_localize(None)
        return self.read_range(end - pd.Timedelta(minutes=minutes), end, sample_seconds)

    def read_range(
        self,
        start: str | datetime,
        end: str | datetime,
        sample_seconds: int,
        *,
        tags: list[str] | None = None,
        include_boundary: bool = True,
    ) -> pd.DataFrame:
        start_stamp = _local(start, self.config.timezone)
        end_stamp = _local(end, self.config.timezone)
        wanted = list(tags if tags is not None else self.config.tags)
        seconds = sample_seconds if self.config.type in RESAMPLING_SOURCES else 0
        with self._lock:
            spans = self.cache.spans(self.key, wanted)
            # Group tags by the instant their missing data starts (and the
            # resolution it is read at), so tags cached together are fetched
            # together in one source call.
            fetches: dict[tuple[pd.Timestamp, int], list[str]] = defaultdict(list)
            for tag in wanted:
                span = spans.get(tag)
                if span and span[0] <= start_stamp and span[2] <= seconds:
                    if span[1] < end_stamp:
                        # A tail keeps the span's own (finer) resolution.
                        tail_start = max(span[0], span[1] - LATE_SAMPLES)
                        fetches[(tail_start, span[2] or seconds)].append(tag)
                else:
                    fetches[(start_stamp, seconds)].append(tag)
            self.last_read_from_cache = not fetches
            failures: list[tuple[str, str]] = []
            cutoff = end_stamp - self.retention if self.retention else None
            for (fetch_start, fetch_seconds), group in fetches.items():
                # A tail with no new values yet (or a brief outage) is not an
                # error: the cached part still answers and the next read retries.
                tail = fetch_start != start_stamp
                try:
                    frame = self.source.read_range(
                        fetch_start,
                        end_stamp,
                        fetch_seconds or sample_seconds,
                        tags=group,
                        include_boundary=include_boundary and not tail,
                    )
                except Exception:
                    if not tail:
                        raise
                    continue
                failed = dict(self.source.failed_tags)
                samples, new_spans = {}, {}
                for tag in group:
                    column = self._column(tag)
                    if tag in failed or column not in frame.columns:
                        if not tail:
                            failures.append((tag, failed.get(tag, "no data")))
                        continue
                    samples[tag] = frame[column]
                    previous = spans.get(tag) if tail else None
                    covered = end_stamp
                    if previous is not None:
                        if covered > previous[1]:
                            new_spans[tag] = (previous[0], covered, previous[2])
                    else:
                        new_spans[tag] = (start_stamp, max(covered, start_stamp), fetch_seconds)
                self.cache.store(self.key, samples, new_spans, cutoff)
            frame = self.cache.load(self.key, wanted, start_stamp, end_stamp)
            self.source.failed_tags = failures
            if frame.empty:
                details = "; ".join(f"{tag}: {reason}" for tag, reason in failures[:5])
                raise RuntimeError(
                    t("No tag was loaded from the source. {details}", details=details)
                )
            return frame.rename(columns=self._column)

    def _column(self, tag: str) -> str:
        return self.config.mapping.get(tag, tag)


def _local(value: str | datetime | pd.Timestamp, timezone: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(timezone).tz_localize(None)
    return stamp


def build_cached_source(config: DataSourceConfig, db: Database | None) -> DataSource:
    """The configured source, behind the history cache when it helps."""

    source = build_source(config)
    if db is None or config.type == "csv" or config.history_cache_hours <= 0:
        return source
    cache = HistoryCache(db)
    if os.environ.get("PLANTCRAFT_RESET_HISTORY_CACHE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        cache.clear(source_key(config))
    return CachedSource(source, cache, config)
