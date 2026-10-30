"""Connection status, signal browsing and history reads for one source."""

from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd

from plantcraft.config import DataSourceConfig
from plantcraft.i18n import t
from plantcraft.industrial_data.sources import DataSource

SIGNALS_TTL_SECONDS = 300
STATUS_TTL_SECONDS = 15


class IndustrialData:
    def __init__(self, config: DataSourceConfig, source: DataSource):
        self.config = config
        self.source = source
        self._lock = threading.Lock()
        self._signals: tuple[float, list[dict[str, Any]]] | None = None
        self._status: tuple[float, dict[str, Any]] | None = None

    def prewarm(
        self,
        hours: float,
        *,
        sample_seconds: int = 30,
        batch_size: int = 16,
        stop: threading.Event | None = None,
    ) -> int:
        """Fill the history cache for every configured tag, a few tags at a time.

        Small batches release the source between reads, so monitoring cycles
        are never blocked for long. ``sample_seconds`` should be the finest
        resolution the rounds read (the analysis resample): a coarser span is
        read again by a finer read. Returns the number of tags read.
        """

        if not hasattr(self.source, "cache"):
            return 0
        end = pd.Timestamp.now(tz=self.config.timezone).tz_localize(None)
        start = end - pd.Timedelta(hours=hours)
        done = 0
        for offset in range(0, len(self.config.tags), batch_size):
            if stop is not None and stop.is_set():
                break
            batch = self.config.tags[offset : offset + batch_size]
            try:
                self.source.read_range(start, end, sample_seconds, tags=batch)
                done += len(batch)
            except Exception:  # a missing tag must not stop the warm-up
                continue
        return done

    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            if (
                not refresh
                and self._status
                and time.monotonic() - self._status[0] < STATUS_TTL_SECONDS
            ):
                return self._status[1]
            started = time.perf_counter()
            try:
                detail = self.source.test_connection()
                result = {"ok": True, "message": detail or t("Connection established.")}
            except Exception as exc:  # the message is shown to the engineer
                result = {"ok": False, "message": str(exc) or type(exc).__name__}
            result["latency_ms"] = round((time.perf_counter() - started) * 1000)
            result["checked_at"] = pd.Timestamp.now(tz=self.config.timezone).isoformat(
                timespec="seconds"
            )
            self._status = (time.monotonic(), result)
            return result

    def signals(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            if (
                not refresh
                and self._signals
                and time.monotonic() - self._signals[0] < SIGNALS_TTL_SECONDS
            ):
                return self._signals[1]
        items = [
            {
                "tag": signal.tag,
                "name": signal.name,
                "asset": signal.asset,
                "unit": signal.unit,
                "description": signal.description,
                "data_type": signal.data_type,
            }
            for signal in self.source.list_signals()
        ]
        items.sort(key=lambda item: (item["asset"], item["tag"]))
        with self._lock:
            self._signals = (time.monotonic(), items)
        return items

    def history(
        self,
        tags: list[str],
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
        sample_seconds: int = 30,
        max_points: int = 1500,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        frame = self.source.read_range(start, end, sample_seconds, tags=tags)
        elapsed = round((time.perf_counter() - started) * 1000)
        columns = {self.config.mapping.get(tag, tag): tag for tag in tags}
        series: dict[str, list[list[Any]]] = {}
        for column, tag in columns.items():
            if column not in frame.columns:
                continue
            values = frame[column].dropna()
            if len(values) > max_points:
                step = len(values) // max_points + 1
                values = pd.concat([values.iloc[::step], values.iloc[-1:]])
                values = values.loc[~values.index.duplicated(keep="last")]
            series[tag] = [
                [stamp.isoformat(), value.item() if hasattr(value, "item") else value]
                for stamp, value in values.items()
            ]
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "series": series,
            "failed_tags": [tag for tag, _ in getattr(self.source, "failed_tags", [])],
            "elapsed_ms": elapsed,
            "from_cache": bool(getattr(self.source, "last_read_from_cache", False)),
        }
