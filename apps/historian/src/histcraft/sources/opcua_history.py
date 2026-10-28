"""OPC UA Historical Access source: raw history of stable string NodeIds.

Ported from PlantCraft (``industrial_data/sources.py``, ``OpcUaHistoricalSource``). A
tag is the string identifier of a node in ``namespace_uri`` (node
``ns=<index of namespace_uri>;s=<tag>``). Read-only: it uses the OPC UA services
HistoryRead, Read, Browse and the namespace array lookup, nothing else.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from histcraft.i18n import t
from histcraft.sources.config import NO_VALUE, SignalInfo, SourceConfig

logger = logging.getLogger(__name__)
_NODE_ID = re.compile(r"^(ns=\d+;|nsu=[^;]+;)?[isgb]=")


def node_id(address: str, namespace_index: int) -> Any:
    """A point's address as a NodeId: a whole NodeId as the collector reads it
    (``ns=2;s=FIC-101.PV``, what Browse gives), or a string identifier in ``namespace_uri``.
    History reads took only the second, so backfill and mode both read nothing for points
    added from Browse (source test kit, 2026-10-24)."""

    from asyncua import ua

    if _NODE_ID.match(address):
        return ua.NodeId.from_string(address)
    return ua.NodeId(address, namespace_index)


# History reads in flight at once on one OPC UA session.
OPCUA_CONCURRENT_READS = int(os.environ.get("HISTCRAFT_OPCUA_CONCURRENT_READS", "16"))
# Browsing stops this deep under Objects.
BROWSE_DEPTH = 6


class OpcUaHistoricalSource:
    """Read raw OPC UA Historical Access values from stable string NodeIds."""

    def __init__(self, config: SourceConfig):
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

    def read_raw(
        self, tags: list[str], start: str | datetime, end: str | datetime
    ) -> dict[str, pd.Series | str]:
        """Per tag, its raw history in [start, end] with the last value before ``start``
        (at its own time), or why it failed. Bad-quality values stay as ``None``."""

        start_utc, end_utc = self._as_utc(start), self._as_utc(end)
        if start_utc >= end_utc:
            raise ValueError(t("The start of the OPC UA read must come before the end."))
        with self._lock:
            return asyncio.run(self._read_tags(start_utc, end_utc, tags, True, False))

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
        wanted = list(tags if tags is not None else self.config.tags)
        with self._lock:
            results = asyncio.run(self._read_tags(start, end, wanted, include_boundary, True))
        failures: list[tuple[str, str]] = []
        series: dict[str, pd.Series] = {}
        for tag, values in results.items():
            error = values if isinstance(values, str) else None
            if error is None and values.dropna().empty:
                error = NO_VALUE + " in the requested interval"
            if error:
                # A step signal (SP, MODE) with no new value since the last
                # read is expected, not a failure worth a warning.
                quiet = error.startswith(NO_VALUE)
                logger.log(
                    logging.DEBUG if quiet else logging.WARNING,
                    "Failed to load OPC UA %s: %s",
                    tag,
                    error,
                )
                failures.append((tag, error))
            else:
                column = self.config.mapping.get(tag, tag)
                series[column] = values.dropna().rename(column)
        self.failed_tags = failures
        if not series:
            details = "; ".join(f"{tag}: {reason}" for tag, reason in failures[:5])
            raise RuntimeError(
                t("No tag was loaded from the OPC UA server. {details}", details=details)
            )
        frame = pd.concat(series.values(), axis=1).sort_index()
        return frame.loc[~frame.index.duplicated(keep="last")]

    async def _client(self):
        from asyncua import Client

        from histcraft.sources import certificates

        client = Client(self.config.endpoint_url or "", timeout=self.config.timeout_seconds)
        options = {
            "security_mode": self.config.security_mode,
            "security_policy": self.config.security_policy,
            "server_thumbprint": self.config.server_thumbprint,
        }
        data_dir = Path(self.config.data_dir) if self.config.data_dir else None
        await certificates.secure(
            client, self.config.endpoint_url or "", options, data_dir, self.config.timeout_seconds
        )
        if self.config.auth_type == "basic":
            password = self.config.secret()
            if not self.config.username:
                raise ValueError(t("OPC UA with user and password needs the user name."))
            client.set_user(self.config.username)
            if password:
                client.set_password(password)
        return client

    async def _namespace_index(self, client) -> int:
        try:
            return await client.get_namespace_index(self.config.namespace_uri)
        except ValueError as exc:
            raise ValueError(
                t(
                    "The OPC UA server does not publish the namespace {uri}.",
                    uri=self.config.namespace_uri,
                )
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        """Connect and look the namespace up; raise when either fails."""

        async def check() -> dict[str, Any]:
            async with await self._client() as client:
                namespaces = await client.get_namespace_array()
                index = await self._namespace_index(client)
                return {"namespace_index": index, "namespaces": len(namespaces)}

        with self._lock:
            return asyncio.run(check())

    def list_signals(self, limit: int | None = None) -> tuple[list[SignalInfo], bool]:
        """Variables with a string NodeId in ``namespace_uri``; whether the list was cut."""

        with self._lock:
            return asyncio.run(self._browse(limit))

    async def _browse(self, limit: int | None) -> tuple[list[SignalInfo], bool]:
        from asyncua import ua

        signals: list[SignalInfo] = []
        truncated = False
        async with await self._client() as client:
            namespace_index = await self._namespace_index(client)

            async def walk(node, path: list[str], depth: int) -> None:
                nonlocal truncated
                if depth > BROWSE_DEPTH or truncated:
                    return
                variables, objects, properties = [], [], {}
                for child in await node.get_children():
                    if child.nodeid.NamespaceIndex != namespace_index:
                        continue
                    node_class = await child.read_node_class()
                    name = (await child.read_browse_name()).Name
                    if node_class == ua.NodeClass.Object:
                        objects.append((child, name))
                    elif node_class == ua.NodeClass.Variable:
                        if await _is_property(child):
                            properties[name] = await child.read_value()
                        elif isinstance(child.nodeid.Identifier, str):
                            variables.append((child, name))
                unit = str(properties.get("EngineeringUnit") or "")
                description = str(properties.get("Name") or properties.get("Description") or "")
                for child, name in variables:
                    if limit is not None and len(signals) >= limit:
                        truncated = True
                        return
                    variant = await child.read_data_type_as_variant_type()
                    text = variant in (ua.VariantType.String, ua.VariantType.LocalizedText)
                    signals.append(
                        SignalInfo(
                            tag=child.nodeid.Identifier,
                            name=name,
                            asset=path[-1] if path else "",
                            # The asset unit belongs to the process value and its setpoint.
                            unit=unit if name.upper() in {"PV", "SP"} else "",
                            description=description,
                            data_type="text" if text else "number",
                            step=text or variant == ua.VariantType.Boolean,
                            path="/".join([*path, name]),
                        )
                    )
                for child, name in objects:
                    await walk(child, [*path, name], depth + 1)

            await walk(client.nodes.objects, [], 0)
        return signals, truncated

    async def _read_tags(
        self,
        start: datetime,
        end: datetime,
        tags: list[str],
        include_boundary: bool,
        boundary_at_start: bool,
    ) -> dict[str, pd.Series | str]:

        client = await self._client()
        boundary_start = start - timedelta(minutes=self.config.history_boundary_minutes)
        local_start = pd.Timestamp(start).tz_convert(self.config.timezone).tz_localize(None)
        local_end = pd.Timestamp(end).tz_convert(self.config.timezone).tz_localize(None)
        async with client:
            namespace_index = await self._namespace_index(client)

            async def read_tag(tag: str) -> pd.Series | str:
                try:
                    node = client.get_node(node_id(tag, namespace_index))
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
                    stamped = [item for item in values if item.SourceTimestamp is not None]
                    if not stamped:
                        # No history: say so when the node itself does not exist.
                        await node.read_node_class()
                        return pd.Series(dtype=object, name=tag)
                    index = (
                        pd.to_datetime([item.SourceTimestamp for item in stamped], utc=True)
                        .tz_convert(self.config.timezone)
                        .tz_localize(None)
                    )
                    # Bad quality is a gap, never a value.
                    result = pd.Series(
                        [
                            _plain(item.Value.Value if item.Value is not None else None)
                            if item.StatusCode.is_good()
                            else None
                            for item in stamped
                        ],
                        index=index,
                        name=tag,
                        dtype=object,
                    )
                    result = result.loc[~result.index.duplicated(keep="last")].sort_index()
                    before = result.loc[result.index < local_start].dropna()
                    result = result.loc[local_start:local_end]
                    if not before.empty:
                        stamp = local_start if boundary_at_start else before.index[-1]
                        if stamp not in result.index:
                            result.loc[stamp] = before.iloc[-1]
                            result = result.sort_index()
                    return result
                except Exception as exc:
                    return str(exc) or type(exc).__name__

            # Servers limit history reads per session (continuation points).
            limit = asyncio.Semaphore(OPCUA_CONCURRENT_READS)

            async def bounded(tag: str) -> pd.Series | str:
                async with limit:
                    return await read_tag(tag)

            results = await asyncio.gather(*(bounded(tag) for tag in tags))
        return dict(zip(tags, results, strict=True))


def _plain(value: Any) -> Any:
    """An OPC UA value as a number or a label; anything else is a gap."""

    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return value
    text = getattr(value, "Text", None)  # LocalizedText
    return text if isinstance(text, str) else None


async def _is_property(node) -> bool:
    """Properties (name, description, unit) describe an asset; they are not signals."""

    from asyncua import ua

    type_definition = await node.read_type_definition()
    return type_definition == ua.NodeId(ua.ObjectIds.PropertyType)
