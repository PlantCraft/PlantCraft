"""The one interface HistCraft calls to read history from a plant source.

``open_source(row, password)`` answers a ``SourceHistory`` for a PI Web API, OPC UA
(Historical Access) or CSV source. Every call is synchronous (it runs in a worker
thread); times go in and come out as UTC epoch milliseconds. Addresses: the PI tag
name, the string identifier of an OPC UA node in ``namespace_uri``, or a CSV column.

The adapters read with their ``timezone`` set to UTC here: their naive frames are
then UTC, and no local time is ever turned back into UTC (no daylight-saving guess).
The source's own time zone is used only for naive times written in a CSV file.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Protocol

import numpy as np
import pandas as pd

from histcraft.i18n import t
from histcraft.sources.config import SignalInfo, SourceConfig, from_source

BROWSE_LIMIT = 20_000


class SourceHistory(Protocol):
    def recorded(
        self, addresses: list[str], start_ms: int, end_ms: int
    ) -> dict[str, tuple[np.ndarray, Any] | str]:
        """Per address: (times in UTC epoch ms, int64 ascending; values) covering [start, end]
        plus the last value before start, or an error string for that address. Values: a
        float64 numpy array for numbers (NaN = gap/bad), or a list for text (None = gap)."""

    def browse(self, root: str | None = None, limit: int = BROWSE_LIMIT) -> dict[str, Any]:
        """{"variables": [{"address", "tag", "name", "path", "kind", "step", "unit",
        "description", "low", "high"}], "truncated": bool, "limit": int}."""

    def test(self) -> dict[str, Any]:
        """Raise with a readable message when unreachable; else what answered."""


def open_source(source: dict[str, Any], password: str) -> SourceHistory:
    """The history reader of a HistCraft source row; ``ValueError`` for another kind."""

    config = from_source(source, password)
    if config.type == "pi_web_api":
        return PiHistory(config)
    if config.type == "opcua":
        return OpcUaHistory(config)
    return CsvHistory(source)


# --- Conversions --------------------------------------------------------------------------


def _check_window(start_ms: int, end_ms: int) -> None:
    if int(start_ms) > int(end_ms):
        raise ValueError(t("The start of the read must come before the end."))


def _utc(ms: int) -> pd.Timestamp:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC")


def _naive_utc_ms(index: pd.Index) -> np.ndarray:
    """Epoch ms of a naive index that holds UTC times (the adapters read in UTC here)."""

    stamps = pd.DatetimeIndex(index)
    if stamps.tz is not None:
        stamps = stamps.tz_convert("UTC").tz_localize(None)
    return (stamps.as_unit("ns").asi8 // 1_000_000).astype(np.int64)


def _number(value: Any) -> float:
    if value is None or isinstance(value, str):
        return np.nan
    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def _gap(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def values_of(raw: list[Any]) -> np.ndarray | list[Any]:
    """Numbers as float64 (NaN for a gap); any text makes the whole series text."""

    if any(isinstance(value, str) for value in raw):
        return [None if _gap(value) else str(value) for value in raw]
    return np.array([_number(value) for value in raw], dtype=np.float64)


def _pack(times: np.ndarray, raw: list[Any]) -> tuple[np.ndarray, Any]:
    times = np.asarray(times, dtype=np.int64)
    order = np.argsort(times, kind="stable")
    times = times[order]
    raw = [raw[i] for i in order]
    # One value per time: the last one read wins.
    if times.size:
        keep = np.r_[times[1:] != times[:-1], True]
        times = times[keep]
        raw = [value for value, kept in zip(raw, keep, strict=True) if kept]
    return times, values_of(raw)


def _series_result(series: pd.Series) -> tuple[np.ndarray, Any]:
    if series.empty:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
    return _pack(_naive_utc_ms(series.index), list(series.to_numpy(dtype=object)))


def _variable(signal: SignalInfo, address: str) -> dict[str, Any]:
    return {
        "address": address,
        "tag": signal.tag,
        "name": signal.name,
        "path": signal.path or signal.tag,
        "kind": signal.data_type,
        "step": bool(signal.step),
        "unit": signal.unit,
        "description": signal.description,
        "low": None,
        "high": None,
    }


def _pi_range(point: dict[str, Any], text: bool) -> dict[str, float | None]:
    """A PI point's range: ``Zero`` to ``Zero + Span`` (round 8 D2); none for text points or
    a span that is not above 0."""

    try:
        zero, span = float(point.get("Zero")), float(point.get("Span"))
    except (TypeError, ValueError):
        return {"low": None, "high": None}
    if text or not (math.isfinite(zero) and math.isfinite(span)) or span <= 0:
        return {"low": None, "high": None}
    return {"low": zero, "high": zero + span}


def _limit(limit: int) -> int:
    return max(1, min(int(limit), BROWSE_LIMIT * 10))


# --- PI Web API ---------------------------------------------------------------------------


class PiHistory:
    """Recorded events of PI Points (PI tag names) through PI Web API."""

    def __init__(self, config: SourceConfig):
        # Imported here: a HistCraft without PI sources never loads requests.
        from histcraft.sources.pi_web_api import PiWebApiSource

        if not config.base_url:
            raise ValueError(t("The PI Web API source needs its address."))
        if not config.server:
            raise ValueError(t("The PI Web API source needs the server name."))
        self.config = config
        self.source = PiWebApiSource(replace(config, timezone="UTC"))

    def recorded(
        self, addresses: list[str], start_ms: int, end_ms: int
    ) -> dict[str, tuple[np.ndarray, Any] | str]:
        _check_window(start_ms, end_ms)
        results = self.source.read_recorded(list(addresses), _utc(start_ms), _utc(end_ms))
        return {
            tag: value if isinstance(value, str) else _series_result(value)
            for tag, value in results.items()
        }

    def browse(self, root: str | None = None, limit: int = BROWSE_LIMIT) -> dict[str, Any]:
        limit = _limit(limit)
        name_filter = (root or "").strip() or "*"
        if "*" not in name_filter and "?" not in name_filter:
            name_filter += "*"
        points, truncated = self.source.search_points(name_filter, limit)
        variables = []
        for point in points:
            name = str(point.get("Name") or "")
            if not name:
                continue
            text = str(point.get("PointType") or "").lower() in {"digital", "string"}
            variables.append(
                {
                    "address": name,
                    "tag": name,
                    "name": name,
                    "path": name,
                    "kind": "text" if text else "number",
                    "step": bool(point.get("Step")) or text,
                    "unit": str(point.get("EngineeringUnits") or ""),
                    "description": str(point.get("Descriptor") or ""),
                    **_pi_range(point, text),
                }
            )
        return {"variables": variables, "truncated": truncated, "limit": limit}

    def test(self) -> dict[str, Any]:
        from histcraft.sources.pi_web_api import PiError

        server = self.source.data_server()
        try:
            user = self.source.user().get("Name")
        except PiError:
            user = None
        return {
            "server": server.get("Name"),
            "version": server.get("ServerVersion"),
            "user": user,
        }


# --- OPC UA Historical Access -------------------------------------------------------------


class OpcUaHistory:
    """Raw history of string NodeIds in ``namespace_uri`` (OPC UA HistoryRead)."""

    def __init__(self, config: SourceConfig):
        if not (config.endpoint_url or "").startswith("opc.tcp://"):
            raise ValueError(t("The OPC UA source needs an opc.tcp:// address."))
        if not config.namespace_uri:
            raise ValueError(t("The OPC UA source needs its namespace URI."))
        from histcraft.sources.opcua_history import OpcUaHistoricalSource

        self.config = config
        self.source = OpcUaHistoricalSource(replace(config, timezone="UTC"))

    def recorded(
        self, addresses: list[str], start_ms: int, end_ms: int
    ) -> dict[str, tuple[np.ndarray, Any] | str]:
        _check_window(start_ms, end_ms)
        if start_ms == end_ms:
            end_ms += 1  # HistoryRead needs a window, not an instant
        try:
            results = self.source.read_raw(list(addresses), _utc(start_ms), _utc(end_ms))
        except Exception as exc:  # the server, not one address, failed
            error = str(exc) or type(exc).__name__
            return {address: error for address in addresses}
        return {
            tag: value if isinstance(value, str) else _series_result(value)
            for tag, value in results.items()
        }

    def browse(self, root: str | None = None, limit: int = BROWSE_LIMIT) -> dict[str, Any]:
        limit = _limit(limit)
        signals, truncated = self.source.list_signals(None if root else limit)
        if root:
            prefix = root.strip("/")
            signals = [
                s
                for s in signals
                if s.path == prefix or s.path.startswith(prefix + "/") or s.tag.startswith(root)
            ]
            truncated = len(signals) > limit
            signals = signals[:limit]
        return {
            "variables": [_variable(s, s.tag) for s in signals],
            "truncated": truncated,
            "limit": limit,
        }

    def test(self) -> dict[str, Any]:
        answer = self.source.test_connection()
        return {
            "endpoint": self.config.endpoint_url,
            "namespace_uri": self.config.namespace_uri,
            **answer,
        }


# --- CSV file -----------------------------------------------------------------------------


class CsvHistory:
    """The files of a CSV source (``sources.csv_watch``): one file or a pattern in one folder,
    read whole, every file's values merged by tag."""

    def __init__(self, source: dict[str, Any]):
        from histcraft.sources.csv_watch import CsvWatcher

        if not source.get("endpoint"):
            raise ValueError(t("The CSV source needs the path of its file."))
        self.watcher = CsvWatcher(source)

    def recorded(
        self, addresses: list[str], start_ms: int, end_ms: int
    ) -> dict[str, tuple[np.ndarray, Any] | str]:
        _check_window(start_ms, end_ms)
        try:
            found = self.watcher.check()
        except Exception as exc:  # the files, not one column, failed
            error = str(exc) or type(exc).__name__
            return {address: error for address in addresses}
        out: dict[str, tuple[np.ndarray, Any] | str] = {}
        for address in addresses:
            series = found.get(address)
            if series is None:
                out[address] = t("The file has no column {column}.", column=address)
                continue
            first = int(np.searchsorted(series.times, int(start_ms), side="left"))
            last = int(np.searchsorted(series.times, int(end_ms), side="right"))
            rows = range(max(first - 1, 0), last)
            out[address] = _pack(series.times[list(rows)], [series.values[i] for i in rows])
        return out

    def browse(self, root: str | None = None, limit: int = BROWSE_LIMIT) -> dict[str, Any]:
        limit = _limit(limit)
        variables = self.watcher.browse()["variables"]
        if root:
            variables = [item for item in variables if item["tag"].startswith(root)]
        return {"variables": variables[:limit], "truncated": len(variables) > limit, "limit": limit}

    def test(self) -> dict[str, Any]:
        return self.watcher.test()
