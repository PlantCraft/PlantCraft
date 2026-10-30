"""Data-source adapters and sparse PI-recorded preprocessing.

The PI Web API adapter lives in ``pi_web_api.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import pandas as pd

from plantcraft.config import DataSourceConfig, LoopConfig
from plantcraft.i18n import t

# Start of a per-tag error that only says the tag had nothing new (quiet in the logs).
NO_VALUE = "no value"

logger = logging.getLogger(__name__)
# History reads in flight at once on one OPC UA session.
OPCUA_CONCURRENT_READS = int(os.environ.get("PLANTCRAFT_OPCUA_CONCURRENT_READS", "16"))


@dataclass(frozen=True)
class SignalInfo:
    tag: str
    name: str
    asset: str
    unit: str = ""
    description: str = ""
    data_type: str = "number"


class DataSource(Protocol):
    failed_tags: list[tuple[str, str]]

    def read_window(self, minutes: int, sample_seconds: int) -> pd.DataFrame:
        """Return source data with a DatetimeIndex."""

    def read_range(
        self,
        start: str | datetime,
        end: str | datetime,
        sample_seconds: int,
        *,
        tags: list[str] | None = None,
        include_boundary: bool = True,
    ) -> pd.DataFrame:
        """Return source data for an explicit engineering-analysis interval.

        ``tags`` limits the read to some configured or browsed tags.
        ``include_boundary`` asks for the last value before ``start`` too, so
        step signals such as SP and MODE are known from the first instant.
        """

    def list_signals(self) -> list[SignalInfo]:
        """Signals the source can serve, for the signal browser."""

    def test_connection(self) -> str | None:
        """Raise with a readable message when the source is unreachable.

        May return a one-line description of what answered (server, user).
        """


class CsvRecordedSource:
    """Read a wide, sparse CSV produced by the PI recorded extractor."""

    def __init__(self, config: DataSourceConfig):
        self.config = config
        self.path = Path(config.path or "").expanduser().resolve()
        self.failed_tags: list[tuple[str, str]] = []
        self._frame = pd.DataFrame()
        self._signature: tuple[int, int] | None = None
        self._lock = threading.Lock()

    def _load(self) -> pd.DataFrame:
        if not self.path.is_file():
            raise FileNotFoundError(t("Data file not found: {path}", path=self.path))

        stat = self.path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if self._signature == signature and not self._frame.empty:
                return self._frame

            frame = pd.read_csv(
                self.path,
                index_col=0,
                parse_dates=True,
                low_memory=False,
            )
            frame.index = pd.to_datetime(frame.index, errors="coerce")
            frame = frame.loc[~frame.index.isna()]
            frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()
            self._frame = frame
            self._signature = signature
            return self._frame

    def last_time(self) -> pd.Timestamp | None:
        """The file's last sample time, without copying the file's values."""

        frame = self._load()
        return None if frame.empty else frame.index.max()

    def read_window(self, minutes: int, sample_seconds: int) -> pd.DataFrame:
        frame = self._load()
        if frame.empty:
            return frame.copy()
        end = frame.index.max()
        start = end - pd.Timedelta(minutes=minutes)
        return frame.loc[start:end].copy()

    def read_range(
        self,
        start: str | datetime,
        end: str | datetime,
        sample_seconds: int,
        *,
        tags: list[str] | None = None,
        include_boundary: bool = True,
    ) -> pd.DataFrame:
        frame = self._load()
        if tags is not None:
            frame = frame[[tag for tag in tags if tag in frame.columns]]
        if frame.empty:
            return frame.copy()
        start_stamp = pd.Timestamp(start)
        end_stamp = pd.Timestamp(end)
        if start_stamp.tzinfo is not None:
            start_stamp = start_stamp.tz_localize(None)
        if end_stamp.tzinfo is not None:
            end_stamp = end_stamp.tz_localize(None)
        return frame.loc[start_stamp:end_stamp].copy()

    def list_signals(self) -> list[SignalInfo]:
        frame = self._load()
        return [
            SignalInfo(
                tag=str(column),
                name=str(column),
                asset=asset_from_tag(str(column)),
                data_type="number" if pd.api.types.is_numeric_dtype(frame[column]) else "text",
            )
            for column in frame.columns
        ]

    def test_connection(self) -> None:
        self._load()


class OpcUaHistoricalSource:
    """Read raw OPC UA Historical Access values from stable string NodeIds."""

    def __init__(self, config: DataSourceConfig):
        self.config = config
        self.failed_tags: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def _as_utc(self, value: str | datetime) -> datetime:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize(self.config.timezone)
        return stamp.tz_convert("UTC").to_pydatetime()

    def read_window(self, minutes: int, sample_seconds: int) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        return self._read_between(start, end)

    def read_range(
        self,
        start: str | datetime,
        end: str | datetime,
        sample_seconds: int,
        *,
        tags: list[str] | None = None,
        include_boundary: bool = True,
    ) -> pd.DataFrame:
        return self._read_between(
            self._as_utc(start),
            self._as_utc(end),
            tags=tags,
            include_boundary=include_boundary,
        )

    def _read_between(
        self,
        start: datetime,
        end: datetime,
        *,
        tags: list[str] | None = None,
        include_boundary: bool = True,
    ) -> pd.DataFrame:
        if start >= end:
            raise ValueError(t("The start of the OPC UA read must come before the end."))
        with self._lock:
            return asyncio.run(
                self._read_between_async(
                    start,
                    end,
                    list(tags if tags is not None else self.config.tags),
                    include_boundary,
                )
            )

    def _client(self):
        try:
            from asyncua import Client
        except ImportError as exc:
            raise ImportError(
                t(
                    "The OPC UA source needs the optional dependency: python3 -m pip install -e '.[opcua]'."
                )
            ) from exc

        client = Client(self.config.endpoint_url or "", timeout=self.config.timeout_seconds)
        if self.config.auth_type == "basic":
            password = self.config.secret()
            if not self.config.username or not password:
                raise ValueError(
                    t(
                        "OPC UA with user and password needs username and the password (or a valid password_env)."
                    )
                )
            client.set_user(self.config.username)
            client.set_password(password)
        return client

    def test_connection(self) -> None:
        async def check() -> None:
            async with self._client() as client:
                await client.get_namespace_index(self.config.namespace_uri)

        with self._lock:
            asyncio.run(check())

    def list_signals(self) -> list[SignalInfo]:
        with self._lock:
            return asyncio.run(self._browse())

    async def _browse(self) -> list[SignalInfo]:
        from asyncua import ua

        signals: list[SignalInfo] = []
        async with self._client() as client:
            namespace_index = await client.get_namespace_index(self.config.namespace_uri)

            async def walk(node, asset: str, depth: int) -> None:
                if depth > 6:
                    return
                variables, properties = [], {}
                for child in await node.get_children():
                    if child.nodeid.NamespaceIndex != namespace_index:
                        continue
                    node_class = await child.read_node_class()
                    name = (await child.read_browse_name()).Name
                    if node_class == ua.NodeClass.Object:
                        await walk(child, name, depth + 1)
                    elif node_class == ua.NodeClass.Variable:
                        if await _is_property(child):
                            properties[name] = await child.read_value()
                        elif isinstance(child.nodeid.Identifier, str):
                            variables.append((child, name))
                unit = str(properties.get("EngineeringUnit") or "")
                description = str(properties.get("Name") or properties.get("Description") or "")
                for child, name in variables:
                    variant = await child.read_data_type_as_variant_type()
                    signals.append(
                        SignalInfo(
                            tag=child.nodeid.Identifier,
                            name=name,
                            asset=asset,
                            # The asset unit belongs to the process value and its setpoint.
                            unit=unit if name.upper() in {"PV", "SP"} else "",
                            description=description,
                            data_type="text" if variant == ua.VariantType.String else "number",
                        )
                    )

            await walk(client.nodes.objects, "", 0)
        return signals

    async def _read_between_async(
        self,
        start: datetime,
        end: datetime,
        tags: list[str],
        include_boundary: bool,
    ) -> pd.DataFrame:
        from asyncua import ua

        client = self._client()
        boundary_start = start - timedelta(minutes=self.config.history_boundary_minutes)
        failures: list[tuple[str, str]] = []
        series: dict[str, pd.Series] = {}
        async with client:
            namespace_index = await client.get_namespace_index(self.config.namespace_uri)

            async def read_tag(tag: str) -> tuple[str, pd.Series | None, str | None]:
                try:
                    node = client.get_node(ua.NodeId(tag, namespace_index))
                    values = await node.read_raw_history(
                        start,
                        end,
                        numvalues=0,
                        return_bounds=False,
                    )
                    if include_boundary and self.config.history_boundary_minutes:
                        # Reading backwards with one value returns the last
                        # sample before ``start`` without scanning the boundary.
                        previous = await node.read_raw_history(
                            start - timedelta(microseconds=1),
                            boundary_start,
                            numvalues=1,
                            return_bounds=False,
                        )
                        values = [*previous, *values]
                    good = [
                        item
                        for item in values
                        if item.SourceTimestamp is not None and item.StatusCode.is_good()
                    ]
                    if not good:
                        raise ValueError(NO_VALUE + " with good quality in history")
                    index = (
                        pd.to_datetime(
                            [item.SourceTimestamp for item in good],
                            utc=True,
                        )
                        .tz_convert(self.config.timezone)
                        .tz_localize(None)
                    )
                    column = self.config.mapping.get(tag, tag)
                    result = pd.Series(
                        [item.Value.Value for item in good],
                        index=index,
                        name=column,
                    )
                    result = result.loc[~result.index.duplicated(keep="last")].sort_index()
                    local_start = (
                        pd.Timestamp(start).tz_convert(self.config.timezone).tz_localize(None)
                    )
                    local_end = pd.Timestamp(end).tz_convert(self.config.timezone).tz_localize(None)
                    before = result.loc[result.index < local_start]
                    result = result.loc[local_start:local_end]
                    if not before.empty and local_start not in result.index:
                        result.loc[local_start] = before.iloc[-1]
                        result = result.sort_index()
                    if result.empty:
                        raise ValueError(NO_VALUE + " in the requested interval")
                    return column, result, None
                except Exception as exc:
                    return tag, None, str(exc)

            # Servers limit history reads per session (continuation points).
            limit = asyncio.Semaphore(OPCUA_CONCURRENT_READS)

            async def bounded(tag: str) -> tuple[str, pd.Series | None, str | None]:
                async with limit:
                    return await read_tag(tag)

            results = await asyncio.gather(*(bounded(tag) for tag in tags))
            for name, values, error in results:
                if error:
                    # A step signal (SP, MODE) with no new value since the last
                    # read is expected, not a failure worth a warning.
                    quiet = error.startswith(NO_VALUE)
                    logger.log(
                        logging.DEBUG if quiet else logging.WARNING,
                        "Failed to load OPC UA %s: %s",
                        name,
                        error,
                    )
                    failures.append((name, error))
                elif values is not None:
                    series[name] = values

        self.failed_tags = failures
        if not series:
            details = "; ".join(f"{tag}: {reason}" for tag, reason in failures[:5])
            raise RuntimeError(
                t("No tag was loaded from the OPC UA server. {details}", details=details)
            )
        frame = pd.concat(series.values(), axis=1).sort_index()
        return frame.loc[~frame.index.duplicated(keep="last")]


async def _is_property(node) -> bool:
    """Properties (name, description, unit) describe an asset; they are not signals."""

    from asyncua import ua

    type_definition = await node.read_type_definition()
    return type_definition == ua.NodeId(ua.ObjectIds.PropertyType)


def asset_from_tag(tag: str) -> str:
    """Group tags like ``FIC-101.PV`` or ``FIC101_PV`` under ``FIC-101``."""

    for separator in (".", ":", "/"):
        if separator in tag:
            return tag.rsplit(separator, 1)[0]
    return tag


def build_source(config: DataSourceConfig) -> DataSource:
    if config.type == "csv":
        return CsvRecordedSource(config)
    if config.type == "pi_web_api":
        from plantcraft.industrial_data.pi_web_api import PiWebApiSource

        return PiWebApiSource(config)
    if config.type == "opcua":
        return OpcUaHistoricalSource(config)
    raise ValueError(t("Unsupported data source: {type}", type=config.type))


def regular_series(
    raw: pd.DataFrame,
    column: str | None,
    grid: pd.DatetimeIndex,
    *,
    step: bool,
) -> pd.Series:
    if not column or column not in raw.columns:
        return pd.Series(index=grid, dtype=float)

    values = raw[column]
    if step:
        clean = values.dropna()
    else:
        clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return pd.Series(index=grid, dtype=float)

    clean = clean.loc[~clean.index.duplicated(keep="last")].sort_index()
    union = clean.index.union(grid)
    expanded = clean.reindex(union).sort_index()
    if step:
        regular = expanded.ffill().reindex(grid)
    else:
        regular = expanded.interpolate(method="time", limit_area="inside").reindex(grid)
    regular = regular.where(grid >= clean.index.min())
    if not step:
        regular = regular.where(grid <= clean.index.max())
    return regular


def build_loop_frame(
    raw: pd.DataFrame,
    loop: LoopConfig,
    sample_seconds: int,
) -> pd.DataFrame:
    """Convert sparse, wide PI data into one regular semantic loop frame."""
    if raw.empty:
        return pd.DataFrame(columns=["timestamp", "pv", "sp", "op", "mode"])

    start = raw.index.min().ceil(f"{sample_seconds}s")
    end = raw.index.max().floor(f"{sample_seconds}s")
    if start > end:
        return pd.DataFrame(columns=["timestamp", "pv", "sp", "op", "mode"])
    grid = pd.date_range(start, end, freq=f"{sample_seconds}s")
    signals = loop.signals

    frame = pd.DataFrame(index=grid)
    frame["timestamp"] = grid
    frame["pv"] = regular_series(raw, signals.pv, grid, step=False)
    frame["sp"] = regular_series(raw, signals.sp, grid, step=True)
    frame["op"] = regular_series(raw, signals.op, grid, step=False)
    if signals.mode:
        frame["mode"] = regular_series(raw, signals.mode, grid, step=True)
    if signals.secondary:
        frame["secondary"] = regular_series(
            raw,
            signals.secondary,
            grid,
            step=False,
        )
    return frame.reset_index(drop=True)
