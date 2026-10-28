"""Reading an OPC UA server: values, browsing and a connection test. Nothing else.

This is the only module of HistCraft that talks to a plant server. It uses the
OPC UA services Read, Browse and the namespace array lookup only;
``tests/test_read_only.py`` fails if any write service (Write, Call,
HistoryUpdate, AddNodes, DeleteNodes...) appears in the code.
"""

from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any

from asyncua import Client, ua

from histcraft.collector.reading import FUTURE_MS, Reading
from histcraft.collector.reading import now_ms as _now_ms
from histcraft.collector.reading import to_ms as _ms
from histcraft.i18n import t
from histcraft.sources import certificates

# An OPC UA node id in text form (``ns=2;s=...``, ``i=85``, ``nsu=...;s=...``).
_NODE_ID = re.compile(r"^(ns=\d+;|nsu=[^;]+;)?[isgb]=")
# Browsing stops after this many variables (a large DCS server has hundreds of thousands).
BROWSE_LIMIT = 20_000
BROWSE_DEPTH = 8


def _plain(value: Any) -> Any:
    """An OPC UA value as a number or a label (anything else is not archived)."""

    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        return value
    if isinstance(value, ua.LocalizedText):
        return value.Text
    return None


class OpcUaReader:
    """One connection to one OPC UA server (anonymous or user and password)."""

    def __init__(
        self,
        source: dict[str, Any],
        *,
        timeout: float = 10.0,
        batch: int = 500,
        password: str = "",
        data_dir: Path | None = None,
    ):
        self.source = source
        # Where the Historian's client certificate lives (a secure channel needs it).
        self.data_dir = data_dir
        self._password = password
        self._namespace_index: int | None = None
        self.timeout = timeout
        self.batch = max(1, batch)
        self.client: Client | None = None
        self._nodes: dict[str, Any] = {}
        self._last_source_ms: dict[str, int] = {}

    async def connect(self) -> None:
        client = Client(url=self.source["endpoint"], timeout=self.timeout)
        await self._secure(client)
        username = self.source.get("username") or ""
        if username:
            client.set_user(username)
            if self._password:
                client.set_password(self._password)
        await client.connect()
        self.client = client
        self._nodes.clear()
        self._namespace_index = None
        if self.source.get("namespace_uri"):
            try:
                self._namespace_index = await client.get_namespace_index(
                    self.source["namespace_uri"]
                )
            except Exception:  # noqa: BLE001 - full node ids still work without it
                self._namespace_index = None

    async def _secure(self, client: Client) -> None:
        """Sign or SignAndEncrypt when the source asks for it (G2, ``sources.certificates``)."""

        await certificates.secure(
            client,
            self.source["endpoint"],
            self.source.get("options") or {},
            self.data_dir,
            self.timeout,
        )

    async def close(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - closing a dead connection may fail any way
                pass

    def _node(self, address: str) -> Any:
        """A node id (``ns=2;s=TI-100.PV``), or a string identifier in the source's namespace
        (``TI-100.PV``, the form sources handed over by PlantCraft use)."""

        node = self._nodes.get(address)
        if node is None:
            assert self.client is not None
            if _NODE_ID.match(address):
                node_id = ua.NodeId.from_string(address)
            elif self._namespace_index is not None:
                node_id = ua.NodeId(address, self._namespace_index)
            else:
                raise ValueError(t("Give a node id (ns=...;s=...) or the source's namespace URI."))
            node = self.client.get_node(node_id)
            self._nodes[address] = node
        return node

    async def read(self, addresses: list[str]) -> dict[str, Reading]:
        """Current value of each address; a bad address answers a bad reading, not an error."""

        assert self.client is not None
        out: dict[str, Reading] = {}
        valid: list[str] = []
        for address in addresses:
            try:
                self._node(address)
                valid.append(address)
            except Exception as exc:  # noqa: BLE001 - a malformed node id is the point's problem
                out[address] = Reading(_now_ms(), None, False, t("Invalid address: {e}", e=exc))
        for offset in range(0, len(valid), self.batch):
            part = valid[offset : offset + self.batch]
            values = await self.client.read_attributes([self._node(a) for a in part])
            read_ms = _now_ms()
            for address, data in zip(part, values, strict=True):
                out[address] = self._reading(address, data, read_ms)
        return out

    def _reading(self, address: str, data: Any, read_ms: int) -> Reading:
        status = data.StatusCode
        source_ms = _ms(data.SourceTimestamp)
        # OPC UA moves the source timestamp only when the value changes: a newer one is the
        # time of the change; otherwise the value still holds at the time it was read (by this
        # clock: servers often leave ServerTimestamp at their start time).
        at = read_ms
        if source_ms is not None and source_ms <= read_ms + FUTURE_MS:
            if source_ms > self._last_source_ms.get(address, -1):
                self._last_source_ms[address] = source_ms
                at = source_ms
        name = getattr(status, "name", "") or "Bad"
        if status is not None and status.is_bad():
            return Reading(at, None, False, name, "bad")
        # Uncertain values are kept, with their quality (G5): a historian records what it read.
        quality = "uncertain" if status is not None and status.is_uncertain() else "good"
        value = _plain(data.Value.Value if data.Value is not None else None)
        if value is None:
            return Reading(at, None, False, t("The value is not a number or text."), "bad")
        return Reading(at, value, True, name if quality != "good" else "", quality)

    async def test(self) -> dict[str, Any]:
        assert self.client is not None
        namespaces = await self.client.get_namespace_array()
        return {"namespaces": namespaces}

    async def browse(self, root: str | None = None, limit: int = BROWSE_LIMIT) -> dict[str, Any]:
        """Variables under ``root`` (default: Objects), with units and ranges when published."""

        assert self.client is not None
        client = self.client
        start = client.get_node(ua.NodeId.from_string(root)) if root else client.nodes.objects
        namespace_index = None
        if self.source.get("namespace_uri"):
            try:
                namespace_index = await client.get_namespace_index(self.source["namespace_uri"])
            except Exception:  # noqa: BLE001 - an unknown namespace browses everything
                namespace_index = None
        found: list[dict[str, Any]] = []
        truncated = False
        deadline = time.monotonic() + max(self.timeout * 6, 60)

        async def walk(node: Any, path: list[str], depth: int, inherited: dict[str, Any]) -> None:
            nonlocal truncated
            if depth > BROWSE_DEPTH or truncated:
                return
            if time.monotonic() > deadline:
                truncated = True
                return
            children = await node.get_children()
            variables, objects, properties = [], [], {}
            for child in children:
                if namespace_index is not None and child.nodeid.NamespaceIndex not in (
                    namespace_index,
                ):
                    continue
                if child.nodeid.NamespaceIndex == 0:
                    continue
                node_class = await child.read_node_class()
                name = (await child.read_browse_name()).Name
                if node_class == ua.NodeClass.Object:
                    objects.append((child, name))
                elif node_class == ua.NodeClass.Variable:
                    if await _is_property(child):
                        try:
                            properties[name] = await child.read_value()
                        except Exception:  # noqa: BLE001 - an unreadable property is skipped
                            pass
                    else:
                        variables.append((child, name))
            context = {
                "unit": _unit(properties) or inherited.get("unit", ""),
                "description": str(properties.get("Description") or properties.get("Name") or "")
                or inherited.get("description", ""),
            }
            for child, name in variables:
                if len(found) >= limit:
                    truncated = True
                    return
                found.append(await _variable(child, name, path, context))
            for child, name in objects:
                await walk(child, [*path, name], depth + 1, context)

        await walk(start, [], 0, {})
        return {"variables": found, "truncated": truncated, "limit": limit}


async def _variable(node: Any, name: str, path: list[str], context: dict[str, Any]) -> dict:
    kind, step = "number", False
    try:
        variant = await node.read_data_type_as_variant_type()
        if variant in (ua.VariantType.String, ua.VariantType.LocalizedText):
            kind = "text"
        elif variant == ua.VariantType.Boolean:
            step = True  # on/off: archived as 0 and 1, rebuilt as steps
    except Exception:  # noqa: BLE001 - unknown type: assume a number
        pass
    own: dict[str, Any] = {}
    try:
        for child in await node.get_properties():
            prop_name = (await child.read_browse_name()).Name
            if prop_name in ("EURange", "EngineeringUnits", "EngineeringUnit") or (
                prop_name.startswith("Description") and "Description" not in own
            ):
                key = "Description" if prop_name.startswith("Description") else prop_name
                own[key] = await child.read_value()
    except Exception:  # noqa: BLE001 - servers without properties
        pass
    low = high = None
    eu_range = own.get("EURange")
    if eu_range is not None and hasattr(eu_range, "Low"):
        low, high = float(eu_range.Low), float(eu_range.High)
    unit = _unit(own)
    # The parent's unit belongs to its process value and set point only.
    if not unit and name.upper() in {"PV", "SP"}:
        unit = context.get("unit", "")
    identifier = node.nodeid.Identifier
    tag = identifier if isinstance(identifier, str) else ".".join([*path, name])
    return {
        "address": node.nodeid.to_string(),
        "tag": tag,
        "name": name,
        "path": "/".join([*path, name]),
        "kind": kind,
        "step": step,
        "unit": unit,
        "description": _text(own.get("Description")) or context.get("description") or "",
        "low": low,
        "high": high,
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value.Text or "") if hasattr(value, "Text") else str(value)


def _unit(properties: dict[str, Any]) -> str:
    units = properties.get("EngineeringUnits")
    if units is not None and hasattr(units, "DisplayName"):
        return str(units.DisplayName.Text or "")
    value = properties.get("EngineeringUnit")
    return str(value) if isinstance(value, str) else ""


async def _is_property(node: Any) -> bool:
    try:
        type_definition = await node.read_type_definition()
    except Exception:  # noqa: BLE001
        return False
    return type_definition == ua.NodeId(ua.ObjectIds.PropertyType)
