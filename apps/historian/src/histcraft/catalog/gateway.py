"""The options of the sources the gateway (Telegraf) reads: MQTT, Modbus TCP and SQL.

Each kind takes only what the collector writes into the gateway's configuration
(``collector.gateway``); nothing else of Telegraf can be set from Historian, so a source can
only read: MQTT subscribes, Modbus reads registers and coils, SQL runs one SELECT.
"""

from __future__ import annotations

import re
from typing import Any

from histcraft.i18n import t

OPTIONS: dict[str, dict[str, Any]] = {
    "mqtt": {"topics": [], "qos": 0, "data_format": "value"},
    "modbus": {"slave_id": 1, "timeout_seconds": 5.0, "registers": []},
    "sql": {
        "driver": "postgres",
        "query": "",
        "measurement": "sql",
        "time_column": "",
        "tag_columns": [],
        # A LIMS: each row is a laboratory result (``histcraft.lab``), not a plant value.
        "laboratory": False,
    },
}
MQTT_SCHEMES = ("tcp://", "ssl://", "ws://", "wss://", "mqtt://", "mqtts://")
MQTT_FORMATS = ("value", "json")
REGISTER_TYPES = ("coil", "discrete_input", "holding_register", "input_register")
# Words (16-bit registers) each data type takes; FIXED and UFIXED take their byte order's.
DATA_TYPES = {
    "INT8L": 1,
    "INT8H": 1,
    "UINT8L": 1,
    "UINT8H": 1,
    "INT16": 1,
    "UINT16": 1,
    "INT32": 2,
    "UINT32": 2,
    "INT64": 4,
    "UINT64": 4,
    "FLOAT16-IEEE": 1,
    "FLOAT32-IEEE": 2,
    "FLOAT64-IEEE": 4,
    "FIXED": 0,
    "UFIXED": 0,
}
BYTE_ORDERS = {
    1: ("AB", "BA"),
    2: ("ABCD", "DCBA", "BADC", "CDAB"),
    # Telegraf names all eight bytes of a 64-bit value (plugins/inputs/modbus); a four-letter
    # order saved before the source test kit found this (2026-10-24) is read as its long name.
    4: ("ABCDEFGH", "HGFEDCBA", "BADCFEHG", "GHEFCDAB"),
}
WIDE_ORDERS = dict(zip(BYTE_ORDERS[2], BYTE_ORDERS[4], strict=True))
SQL_DRIVERS = ("postgres", "mysql", "sqlserver")
_NAME = re.compile(r"^[A-Za-z0-9_.:/-]{1,100}$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
# Words that change data or run code: a query holding one is refused (a SELECT reads only).
_WRITES = re.compile(
    r"\b(insert|update|delete|merge|upsert|drop|alter|create|truncate|grant|revoke|exec|"
    r"execute|call|copy|into|lock|vacuum|set|declare|attach|pragma)\b",
    re.IGNORECASE,
)
MAX_REGISTERS = 2000
MAX_TOPICS = 100


def check(kind: str, endpoint: str, options: dict[str, Any]) -> dict[str, Any]:
    """The options of a gateway source, checked and normalized (``ValueError`` says why)."""

    if kind == "mqtt":
        return _mqtt(endpoint, options)
    if kind == "modbus":
        return _modbus(endpoint, options)
    return _sql(endpoint, options)


def _lines(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.replace(",", "\n").splitlines()
    return [str(item).strip() for item in value or [] if str(item).strip()]


def _mqtt(endpoint: str, options: dict[str, Any]) -> dict[str, Any]:
    if not endpoint.startswith(MQTT_SCHEMES):
        raise ValueError(t("An MQTT broker address starts with tcp://, ssl://, ws:// or wss://"))
    topics = _lines(options.get("topics"))
    if not topics:
        raise ValueError(t("Name at least one topic to subscribe to, e.g. plant/#."))
    if len(topics) > MAX_TOPICS:
        raise ValueError(t("At most {count} topics.", count=MAX_TOPICS))
    for topic in topics:
        if any(char in topic for char in '"\\\n') or len(topic) > 300:
            raise ValueError(t("Topic {topic} is not valid.", topic=topic))
    qos = int(options.get("qos") or 0)
    if qos not in (0, 1, 2):
        raise ValueError(t("QoS is 0, 1 or 2."))
    data_format = options.get("data_format") or "value"
    if data_format not in MQTT_FORMATS:
        raise ValueError(t("The message format is value or json."))
    return {"topics": topics, "qos": qos, "data_format": data_format}


SPARKPLUG_SCHEMES = ("tcp://", "ssl://", "mqtt://", "mqtts://")
_GROUP = re.compile(r"^[^+#/\s]{1,100}$")


def check_sparkplug(endpoint: str, options: dict[str, Any]) -> dict[str, Any]:
    """A Sparkplug B source's options, checked (the collector subscribes, never publishes)."""

    if not endpoint.startswith(SPARKPLUG_SCHEMES):
        raise ValueError(t("A Sparkplug B broker address starts with tcp:// or ssl://"))
    group = str(options.get("group_id") or "").strip()
    if group and not _GROUP.match(group):
        raise ValueError(t("A group id has no /, + or # (empty: every group)."))
    qos = int(options.get("qos") if options.get("qos") is not None else 1)
    if qos not in (0, 1):
        raise ValueError(t("QoS is 0 or 1."))
    return {"group_id": group, "qos": qos, "add_on_birth": bool(options.get("add_on_birth"))}


def register_words(data_type: str, byte_order: str) -> int:
    words = DATA_TYPES[data_type]
    return words or max(1, len(byte_order) // 2)  # FIXED: as wide as its byte order


def byte_order_of(data_type: str, byte_order: str) -> str:
    """The byte order as Telegraf names it: all eight letters for a 64-bit type."""

    if DATA_TYPES.get(data_type) == 4:
        return WIDE_ORDERS.get(byte_order, byte_order)
    return byte_order


def _modbus(endpoint: str, options: dict[str, Any]) -> dict[str, Any]:
    if not re.match(r"^tcp://[^\s/:]+(:\d{1,5})?$", endpoint):
        raise ValueError(t("A Modbus TCP address is tcp://host:502."))
    slave = int(options.get("slave_id") if options.get("slave_id") is not None else 1)
    if not 0 <= slave <= 255:
        raise ValueError(t("The slave id is 0 to 255."))
    timeout = float(options.get("timeout_seconds") or 5.0)
    if not 0.1 <= timeout <= 60:
        raise ValueError(t("The timeout is 0.1 to 60 s."))
    registers = []
    names: set[str] = set()
    for number, raw in enumerate(options.get("registers") or [], start=1):
        item = dict(raw)
        name = str(item.get("name", "")).strip()
        kind = str(item.get("type", "holding_register"))
        if not _NAME.match(name):
            raise ValueError(
                t("Register {n}: give it a name (letters, digits, . _ - : /).", n=number)
            )
        if name in names:
            raise ValueError(t("Register {name} is listed twice.", name=name))
        names.add(name)
        if kind not in REGISTER_TYPES:
            raise ValueError(
                t(
                    "Register {name}: the type is one of {names}.",
                    name=name,
                    names=", ".join(REGISTER_TYPES),
                )
            )
        try:
            address = int(item.get("address"))
        except (TypeError, ValueError):
            raise ValueError(t("Register {name}: the address is a number.", name=name)) from None
        if not 0 <= address <= 65535:
            raise ValueError(t("Register {name}: the address is 0 to 65535.", name=name))
        entry: dict[str, Any] = {"name": name, "type": kind, "address": address}
        if kind in ("holding_register", "input_register"):
            data_type = str(item.get("data_type") or "INT16").upper()
            if data_type not in DATA_TYPES:
                raise ValueError(
                    t(
                        "Register {name}: the data type is one of {names}.",
                        name=name,
                        names=", ".join(DATA_TYPES),
                    )
                )
            byte_order = byte_order_of(data_type, str(item.get("byte_order") or "").upper())
            words = DATA_TYPES[data_type] or max(1, len(byte_order) // 2)
            byte_order = byte_order or BYTE_ORDERS[words][0]
            if byte_order not in BYTE_ORDERS.get(words, ()):
                raise ValueError(
                    t(
                        "Register {name}: the byte order of {type} is one of {names}.",
                        name=name,
                        type=data_type,
                        names=", ".join(BYTE_ORDERS.get(words, ())),
                    )
                )
            if address + words - 1 > 65535:
                raise ValueError(t("Register {name}: the address is 0 to 65535.", name=name))
            scale = float(item.get("scale") if item.get("scale") not in (None, "") else 1.0)
            if "8" in data_type and not scale.is_integer():
                # Telegraf keeps a one-byte value an integer: 0.1 would be cut off.
                raise ValueError(
                    t("Register {name}: a one-byte type takes a whole-number scale.", name=name)
                )
            entry.update({"data_type": data_type, "byte_order": byte_order, "scale": scale})
        registers.append(entry)
    if not registers:
        raise ValueError(t("List at least one register or coil to read."))
    if len(registers) > MAX_REGISTERS:
        raise ValueError(t("At most {count} registers.", count=MAX_REGISTERS))
    return {"slave_id": slave, "timeout_seconds": timeout, "registers": registers}


def _sql(endpoint: str, options: dict[str, Any]) -> dict[str, Any]:
    if not endpoint:
        raise ValueError(t("Give the database's connection string (DSN)."))
    if any(char in endpoint for char in '"\n\\'):
        raise ValueError(t("The connection string holds a quote, backslash or line break."))
    driver = options.get("driver") or "postgres"
    if driver not in SQL_DRIVERS:
        raise ValueError(t("The database is one of {names}.", names=", ".join(SQL_DRIVERS)))
    query = str(options.get("query") or "").strip().rstrip(";").strip()
    if not query:
        raise ValueError(t("Write the SELECT that reads the values."))
    if not re.match(r"^(select|with)\b", query, re.IGNORECASE) or ";" in query:
        raise ValueError(t("The query is one SELECT (or WITH ... SELECT): it only reads."))
    found = _WRITES.search(_without_strings(query))
    if found:
        raise ValueError(
            t("The query only reads: {word} is not allowed.", word=found.group(0).upper())
        )
    if '"""' in query or "'''" in query:
        raise ValueError(t("The query holds triple quotes."))
    measurement = str(options.get("measurement") or "sql").strip()
    if not _NAME.match(measurement):
        raise ValueError(t("The measurement is a name (letters, digits, . _ - : /)."))
    time_column = str(options.get("time_column") or "").strip()
    tag_columns = _lines(options.get("tag_columns"))
    for column in [time_column, *tag_columns]:
        if column and not _COLUMN.match(column):
            raise ValueError(t("Column {name} is not a plain column name.", name=column))
    laboratory = bool(options.get("laboratory"))
    if laboratory and (not time_column or len(tag_columns) != 1):
        raise ValueError(
            t(
                "A laboratory source names its sampling time column and one tag column, the "
                "analysis; the query gives value and, if it has them, status, received_at and "
                "approved_at."
            )
        )
    return {
        "driver": driver,
        "query": query,
        "measurement": measurement,
        "time_column": time_column,
        "tag_columns": tag_columns,
        "laboratory": laboratory,
    }


def _without_strings(query: str) -> str:
    """The query with its quoted text blanked, so a word inside a string is not a keyword."""

    return re.sub(r"'(?:[^']|'')*'", "''", query)
