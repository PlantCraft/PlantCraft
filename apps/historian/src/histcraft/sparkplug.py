"""Sparkplug B, read only: the topics a host reads, the payload decoded, births followed.

Sparkplug B (Eclipse Sparkplug 3.0, public specification) puts structure on MQTT: each edge node
publishes on ``spBv1.0/<group>/<type>/<edge node>[/<device>]`` a protobuf payload of metrics.
A *birth* (NBIRTH, DBIRTH) lists every metric of the node or device with its name, data type,
alias and current value; *data* messages (NDATA, DDATA) carry only what changed, often by alias;
a *death* (NDEATH, the node's MQTT will, and DDEATH) says its values are stale.

Historian is a host that only listens. It subscribes to births, data and deaths and never
publishes: no STATE (it is not a primary host application) and no NCMD or DCMD, so it never asks
a node for a rebirth either. Metrics are learnt from the births it sees; a node that was born
before Historian connected is learnt from the names in its data, or at its next birth.

This module holds no network code (``collector.sparkplug`` subscribes): the payload decoder (the
protobuf wire format, written here so no generated code or new dependency is needed) and
``Births``, which turns each message into values at their addresses
(``<group>/<edge node>[/<device>]/<metric>``) and lists what the births described for Browse.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

NAMESPACE = "spBv1.0"
# The message types a listening host reads. NCMD, DCMD and STATE are never subscribed to.
READ_TYPES = ("NBIRTH", "NDEATH", "DBIRTH", "DDEATH", "NDATA", "DDATA")
# Sparkplug data types (specification, section 6.4.16) and the kind of point each becomes.
INTEGER_TYPES = {1: 8, 2: 16, 3: 32, 4: 64, 5: 8, 6: 16, 7: 32, 8: 64}
SIGNED = {1, 2, 3, 4}
FLOAT, DOUBLE, BOOLEAN, STRING, DATETIME, TEXT, UUID = 9, 10, 11, 12, 13, 14, 15
TEMPLATE = 19
KIND_OF_TYPE = {
    **{code: "integer" for code in INTEGER_TYPES},
    FLOAT: "number",
    DOUBLE: "number",
    BOOLEAN: "boolean",
    STRING: "text",
    TEXT: "text",
    UUID: "text",
    DATETIME: "instant",
}
TYPE_NAMES = {
    1: "Int8",
    2: "Int16",
    3: "Int32",
    4: "Int64",
    5: "UInt8",
    6: "UInt16",
    7: "UInt32",
    8: "UInt64",
    9: "Float",
    10: "Double",
    11: "Boolean",
    12: "String",
    13: "DateTime",
    14: "Text",
    15: "UUID",
    16: "DataSet",
    17: "Bytes",
    18: "File",
    19: "Template",
}
# Metrics a node publishes about Sparkplug itself (its session, its commands): not plant values.
SESSION_METRICS = ("bdSeq",)
CONTROL_PREFIXES = ("Node Control/", "Device Control/")
# Properties with the unit and the quality, as edge nodes commonly name them.
UNIT_PROPERTIES = ("engUnit", "EngUnit", "engineeringUnits", "units")
QUALITY_PROPERTY = "Quality"
OFFLINE = "The edge node is offline (death)."
MAX_PAYLOAD = 4 * 1024 * 1024
MAX_DEPTH = 8


class SparkplugError(ValueError):
    """A payload that is not Sparkplug B."""


# The protobuf wire format ------------------------------------------------------------------


def _varint(data: bytes, at: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if at >= len(data) or shift > 63:
            raise SparkplugError("truncated varint")
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, at
        shift += 7


def _fields(data: bytes) -> list[tuple[int, int, Any]]:
    """(field number, wire type, value) of each field; a length-delimited value as bytes."""

    found = []
    at = 0
    while at < len(data):
        key, at = _varint(data, at)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, at = _varint(data, at)
        elif wire == 1:
            if at + 8 > len(data):
                raise SparkplugError("truncated fixed64")
            value, at = data[at : at + 8], at + 8
        elif wire == 2:
            size, at = _varint(data, at)
            if at + size > len(data):
                raise SparkplugError("truncated field")
            value, at = data[at : at + size], at + size
        elif wire == 5:
            if at + 4 > len(data):
                raise SparkplugError("truncated fixed32")
            value, at = data[at : at + 4], at + 4
        else:
            raise SparkplugError(f"wire type {wire}")
        if number == 0:
            raise SparkplugError("field 0")
        found.append((number, wire, value))
    return found


def _text(value: Any) -> str:
    if not isinstance(value, bytes):
        raise SparkplugError("text expected")
    return value.decode("utf-8", "replace")


def _signed(value: int, bits: int) -> int:
    """Sparkplug sends Int8 to Int32 in a uint32 and Int64 in a uint64, as two's complement."""

    if bits == 64:
        return value - (1 << 64) if value >= 1 << 63 else value
    value &= 0xFFFFFFFF
    if value >= 1 << 31:
        return value - (1 << 32)  # widened to 32 bits by the sender
    return value - (1 << bits) if (1 << (bits - 1)) <= value < (1 << bits) else value


@dataclass
class Metric:
    name: str = ""
    alias: int | None = None
    timestamp: int | None = None
    datatype: int = 0
    historical: bool = False
    null: bool = False
    value: Any = None
    properties: dict[str, Any] = field(default_factory=dict)
    # A template instance's members (``template_value``), flattened by ``Births``.
    members: list[Metric] = field(default_factory=list)
    definition: bool = False


@dataclass
class Payload:
    timestamp: int | None = None
    seq: int | None = None
    metrics: list[Metric] = field(default_factory=list)


def _property_set(data: bytes, depth: int) -> dict[str, Any]:
    keys: list[str] = []
    values: list[Any] = []
    for number, _wire, value in _fields(data):
        if number == 1:
            keys.append(_text(value))
        elif number == 2:
            values.append(_property_value(value, depth + 1))
    return dict(zip(keys, values, strict=False))


def _property_value(data: bytes, depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise SparkplugError("properties nested too deep")
    kind, found = 0, None
    for number, _wire, value in _fields(data):
        if number == 1:
            kind = value
        elif number == 2 and value:
            return None
        elif number in (3, 4):
            found = value
        elif number == 5:
            found = struct.unpack("<f", value)[0]
        elif number == 6:
            found = struct.unpack("<d", value)[0]
        elif number == 7:
            found = bool(value)
        elif number == 8:
            found = _text(value)
        elif number == 9:
            found = _property_set(value, depth + 1)
    if isinstance(found, int) and not isinstance(found, bool) and kind in INTEGER_TYPES:
        found = _signed(found, INTEGER_TYPES[kind]) if kind in SIGNED else found
    return found


def _metric(data: bytes, depth: int = 0) -> Metric:
    if depth > MAX_DEPTH:
        raise SparkplugError("templates nested too deep")
    metric = Metric()
    raw: Any = None
    for number, _wire, value in _fields(data):
        if number == 1:
            metric.name = _text(value)
        elif number == 2:
            metric.alias = value
        elif number == 3:
            metric.timestamp = value
        elif number == 4:
            metric.datatype = value
        elif number == 5:
            metric.historical = bool(value)
        elif number == 7:
            metric.null = bool(value)
        elif number == 9:
            metric.properties = _property_set(value, depth)
        elif number in (10, 11):
            raw = value
        elif number == 12:
            raw = struct.unpack("<f", value)[0]
        elif number == 13:
            raw = struct.unpack("<d", value)[0]
        elif number == 14:
            raw = bool(value)
        elif number == 15:
            raw = _text(value)
        elif number == 18:
            for member_number, _w, member in _fields(value):
                if member_number == 2:
                    metric.members.append(_metric(member, depth + 1))
                elif member_number == 5:
                    metric.definition = bool(member)
    metric.value = None if metric.null else _typed(metric.datatype, raw)
    return metric


def _typed(datatype: int, raw: Any) -> Any:
    if raw is None:
        return None
    if datatype in INTEGER_TYPES and isinstance(raw, int) and not isinstance(raw, bool):
        return _signed(raw, INTEGER_TYPES[datatype]) if datatype in SIGNED else raw
    if datatype == BOOLEAN:
        return bool(raw)
    return raw


def decode(data: bytes) -> Payload:
    """A Sparkplug B payload (``SparkplugError`` when it is not one)."""

    if len(data) > MAX_PAYLOAD:
        raise SparkplugError("payload over 4 MB")
    payload = Payload()
    for number, wire, value in _fields(data):
        if number == 1 and wire == 0:
            payload.timestamp = value
        elif number == 2 and wire == 2:
            payload.metrics.append(_metric(value))
        elif number == 3 and wire == 0:
            payload.seq = value
    return payload


# Topics -------------------------------------------------------------------------------------


def topics(group_id: str = "") -> list[str]:
    """The subscriptions of a listening host: births, data and deaths of one group (or all)."""

    group = group_id or "+"
    return [f"{NAMESPACE}/{group}/{kind}/#" for kind in READ_TYPES]


@dataclass(frozen=True)
class Topic:
    group: str
    kind: str
    node: str
    device: str = ""

    @property
    def prefix(self) -> str:
        parts = [self.group, self.node] + ([self.device] if self.device else [])
        return "/".join(parts)


def parse_topic(topic: str) -> Topic | None:
    """A Sparkplug B topic this host reads; None for any other (STATE, commands, others)."""

    parts = topic.split("/")
    if len(parts) not in (4, 5) or parts[0] != NAMESPACE or parts[2] not in READ_TYPES:
        return None
    if any(not part for part in parts):
        return None
    device = parts[4] if len(parts) == 5 else ""
    if parts[2].startswith("D") != bool(device):
        return None
    return Topic(parts[1], parts[2], parts[3], device)


# Births ------------------------------------------------------------------------------------


@dataclass
class Value:
    """A value for the point at ``address`` (None and ``good`` False: stale or null)."""

    address: str
    at_ms: int
    value: Any
    good: bool = True
    quality: str = "good"
    detail: str = ""


@dataclass
class _Known:
    name: str
    datatype: int
    unit: str = ""
    description: str = ""
    value: Any = None
    at_ms: int | None = None


@dataclass
class _Edge:
    """An edge node or one of its devices: its metrics by name and alias, and whether online."""

    online: bool = False
    born: bool = False
    metrics: dict[str, _Known] = field(default_factory=dict)
    aliases: dict[int, str] = field(default_factory=dict)


@dataclass
class _Node:
    bd_seq: int | None = None
    seq: int | None = None
    devices: set[str] = field(default_factory=set)


def _quality(metric: Metric) -> tuple[str, bool]:
    """The quality an edge node gives in the ``Quality`` property (OPC DA codes, as Ignition and
    others send them: 192 and up good, 64 to 191 uncertain, below 64 bad)."""

    code = metric.properties.get(QUALITY_PROPERTY)
    if not isinstance(code, int) or isinstance(code, bool):
        return "good", True
    if code >= 192:
        return "good", True
    if code >= 64:
        return "uncertain", True
    return "bad", False


class Births:
    """What one source learnt from the births, deaths and data it read; ``take`` turns each
    message into values. Not thread-safe: one subscriber feeds it."""

    def __init__(self, limit: int = 20_000):
        self.limit = limit
        self.edges: dict[str, _Edge] = {}
        self.nodes: dict[tuple[str, str], _Node] = {}
        # Data whose alias no birth named (Historian connected after the birth), and messages
        # missing from a node's sequence: counted, never asked for again (that would publish).
        self.unknown_aliases = 0
        self.sequence_gaps = 0
        self.unreadable = 0
        self.messages = 0
        self.last_ms: int | None = None

    def take(self, topic: str, data: bytes, now: int) -> list[Value]:
        found = parse_topic(topic)
        if found is None:
            return []
        try:
            payload = decode(data)
        except SparkplugError:
            self.unreadable += 1
            return []
        self.messages += 1
        self.last_ms = now
        node = self.nodes.setdefault((found.group, found.node), _Node())
        node_prefix = f"{found.group}/{found.node}"
        if found.kind == "NDEATH":
            dead = _metric_value(payload.metrics, "bdSeq")
            if node.bd_seq is not None and dead is not None and dead != node.bd_seq:
                return []  # the will of an older session, after the node was born again
            return self._stale([node_prefix, *(f"{node_prefix}/{d}" for d in node.devices)], now)
        self._sequence(node, found.kind, payload.seq)
        edge = self.edges.setdefault(found.prefix, _Edge())
        if found.kind == "DDEATH":
            return self._stale([found.prefix], now)
        if found.kind in ("NBIRTH", "DBIRTH"):
            if found.kind == "NBIRTH":
                node.bd_seq = _metric_value(payload.metrics, "bdSeq")
                for device in node.devices:
                    self.edges.pop(f"{node_prefix}/{device}", None)
                node.devices.clear()
            else:
                node.devices.add(found.device)
            edge.metrics, edge.aliases = {}, {}
            edge.born = True
        edge.online = True
        return self._values(found, edge, payload, now, birth=found.kind.endswith("BIRTH"))

    def _sequence(self, node: _Node, kind: str, seq: int | None) -> None:
        if seq is None:
            return
        if kind != "NBIRTH" and node.seq is not None and seq != (node.seq + 1) % 256:
            self.sequence_gaps += 1
        node.seq = seq

    def _stale(self, prefixes: list[str], now: int) -> list[Value]:
        out = []
        for prefix in prefixes:
            edge = self.edges.get(prefix)
            if edge is None:
                continue
            edge.online = False
            for name in edge.metrics:
                out.append(Value(f"{prefix}/{name}", now, None, False, "bad", OFFLINE))
        return out

    def _values(
        self, topic: Topic, edge: _Edge, payload: Payload, now: int, *, birth: bool
    ) -> list[Value]:
        out: list[Value] = []
        for metric in _flattened(payload.metrics):
            name = metric.name
            if birth and metric.alias is not None and name:
                edge.aliases[int(metric.alias)] = name
            if not name and metric.alias is not None:
                name = edge.aliases.get(int(metric.alias), "")
            if not name:
                self.unknown_aliases += 1
                continue
            if name in SESSION_METRICS or name.startswith(CONTROL_PREFIXES):
                continue
            if not metric.datatype and not birth:
                metric.datatype = _inferred(metric.value)  # data seen before any birth
            known = edge.metrics.get(name)
            if known is None:
                if metric.datatype not in KIND_OF_TYPE and not (birth and metric.datatype):
                    continue
                if len(edge.metrics) >= self.limit:
                    continue
                known = edge.metrics[name] = _Known(name, metric.datatype)
            if birth or not known.datatype:
                known.datatype = metric.datatype or known.datatype
            unit = next(
                (metric.properties[key] for key in UNIT_PROPERTIES if key in metric.properties),
                None,
            )
            if isinstance(unit, str):
                known.unit = unit[:40]
            if isinstance(metric.properties.get("description"), str):
                known.description = metric.properties["description"][:500]
            if known.datatype not in KIND_OF_TYPE:
                continue  # DataSet, Bytes, File: listed by the birth, not archived
            at = metric.timestamp or payload.timestamp or now
            quality, good = _quality(metric)
            value = metric.value
            if value is None:
                good, quality = False, "bad"
            known.value, known.at_ms = value, at
            out.append(
                Value(
                    f"{topic.prefix}/{name}",
                    int(at),
                    value if good else None,
                    good,
                    quality,
                    "" if good and quality == "good" else ("null" if value is None else quality),
                )
            )
        return out

    def variables(self) -> list[dict[str, Any]]:
        """Every metric the births (or data) described, as Browse lists a variable."""

        found = []
        for prefix, edge in self.edges.items():
            for name, known in edge.metrics.items():
                kind = KIND_OF_TYPE.get(known.datatype)
                address = f"{prefix}/{name}"
                found.append(
                    {
                        "address": address,
                        "tag": address.replace("/", "."),
                        "name": name,
                        "path": address,
                        "kind": kind or "",
                        "datatype": TYPE_NAMES.get(known.datatype, str(known.datatype)),
                        "step": kind not in ("number", None),
                        "unit": known.unit,
                        "description": known.description,
                        "low": None,
                        "high": None,
                        "value": known.value,
                        "at": known.at_ms,
                        "online": edge.online,
                        "born": edge.born,
                    }
                )
        found.sort(key=lambda item: item["tag"])
        return found

    @property
    def known(self) -> int:
        """How many metrics are known: it grows with each new one."""

        return sum(len(edge.metrics) for edge in self.edges.values())

    def summary(self) -> dict[str, Any]:
        return {
            "nodes": len(self.nodes),
            "devices": sum(len(node.devices) for node in self.nodes.values()),
            "metrics": self.known,
            "online": sum(1 for edge in self.edges.values() if edge.online),
            "messages": self.messages,
            "unknown_aliases": self.unknown_aliases,
            "sequence_gaps": self.sequence_gaps,
            "unreadable": self.unreadable,
            "last": self.last_ms,
        }


def _metric_value(metrics: list[Metric], name: str) -> Any:
    return next((metric.value for metric in metrics if metric.name == name), None)


def _inferred(value: Any) -> int:
    """The data type of a value sent without one (data read before its birth)."""

    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, int):
        return 4
    if isinstance(value, float):
        return DOUBLE
    return STRING if isinstance(value, str) else 0


def _flattened(metrics: list[Metric]) -> list[Metric]:
    """Template instances as their members (``Motor1/Speed``); definitions left out."""

    out = []
    for metric in metrics:
        if metric.datatype != TEMPLATE:
            out.append(metric)
        elif metric.name and not metric.definition:
            for member in metric.members:
                member.name = f"{metric.name}/{member.name}"
                member.timestamp = member.timestamp or metric.timestamp
            out += _flattened(metric.members)
    return out
