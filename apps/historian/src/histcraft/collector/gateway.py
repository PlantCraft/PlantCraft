"""The gateway's configuration: Telegraf reads MQTT, Modbus and SQL sources for Historian.

The collector writes ``<data>/gateway/telegraf.conf`` (0600) whenever a gateway source changes;
the ``histcraft-gateway`` service (the official Telegraf image) shares the folder and reloads
it (``--watch-config poll``). Only what is written here runs in the gateway:

- one input per enabled source, from an allow list (``inputs.mqtt_consumer``,
  ``inputs.modbus``, ``inputs.sql``), each tagged ``histcraft_source = "<source id>"``;
- ``inputs.internal``, the gateway's own heartbeat (tagged ``gateway``, never archived);
- one output, ``outputs.influxdb_v2``, to the collector (``collector.ingest``) with the token
  in ``<data>/gateway/token``.

MQTT subscribes, Modbus reads registers and coils, SQL runs the source's SELECT: nothing writes
to a plant system. Every value is a TOML basic string written by ``json.dumps``, so no text a
person typed can add a line, a table or another plugin.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plantcraft_sdk.files import write_atomic

from histcraft.catalog.gateway import byte_order_of, register_words
from histcraft.catalog.models import GATEWAY_KINDS
from histcraft.collector.ingest import GATEWAY_SOURCE, SOURCE_TAG
from histcraft.config import Settings

FOLDER = "gateway"
CONFIG = "telegraf.conf"
TOKEN = "token"
# Telegraf plugins Historian configures; tests/test_read_only.py checks no other appears.
INPUTS = {"mqtt": "mqtt_consumer", "modbus": "modbus", "sql": "sql"}
SQL_DRIVERS = {"postgres": "pgx", "mysql": "mysql", "sqlserver": "sqlserver"}
REGISTER_TABLES = {
    "coil": "coils",
    "discrete_input": "discrete_inputs",
    "holding_register": "holding_registers",
    "input_register": "input_registers",
}


def _quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def _duration(seconds: float) -> str:
    seconds = max(float(seconds), 1.0)
    return f"{int(seconds)}s" if seconds.is_integer() else f"{int(seconds * 1000)}ms"


def _private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` readable by its owner only, replacing it at once."""

    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, text, mode=0o600)


def gateway_token(data_dir: Path) -> str:
    """The token the gateway writes with (made once, kept in ``<data>/gateway/token``)."""

    path = Path(data_dir) / FOLDER / TOKEN
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if not token:
        token = secrets.token_urlsafe(32)
        _private(path, token + "\n")
    return token


def render(
    settings: Settings,
    sources: list[dict[str, Any]],
    password: Callable[[dict[str, Any]], str],
    general_scan: float,
) -> str:
    """The gateway's whole configuration for these sources."""

    lines = [
        "# PlantCraft Historian's gateway. Written by the collector: changes here are replaced",
        "# when a source changes. Sources are set up on Historian's Sources page.",
        "[agent]",
        '  interval = "10s"',
        "  round_interval = true",
        '  flush_interval = "2s"',
        "  metric_batch_size = 1000",
        "  metric_buffer_limit = 100000",
        "  omit_hostname = true",
        "",
        "[[outputs.influxdb_v2]]",
        f"  urls = [{_quote(settings.ingest_url)}]",
        f"  token = {_quote(gateway_token(settings.data_dir))}",
        '  organization = "historian"',
        '  bucket = "historian"',
        '  timeout = "10s"',
        "",
        "[[inputs.internal]]",
        "  collect_memstats = false",
        "  [inputs.internal.tags]",
        f"    {SOURCE_TAG} = {_quote(GATEWAY_SOURCE)}",
    ]
    for source in sorted(sources, key=lambda item: item["id"]):
        if source["kind"] not in GATEWAY_KINDS or not source.get("enabled"):
            continue
        scan = source.get("default_scan_seconds") or general_scan
        lines += ["", *_input(source, password(source) if _signed(source) else "", scan)]
    return "\n".join(lines) + "\n"


def _signed(source: dict[str, Any]) -> bool:
    return bool(
        source.get("username")
        or source.get("has_password")
        or source.get("password_env")
        or "{password}" in source.get("endpoint", "")
    )


def _input(source: dict[str, Any], password: str, scan: float) -> list[str]:
    kind, options = source["kind"], source["options"]
    plugin = INPUTS[kind]
    head = [f"[[inputs.{plugin}]]", f"  alias = {_quote(source['id'])}"]
    tags = [f"  [inputs.{plugin}.tags]", f"    {SOURCE_TAG} = {_quote(source['id'])}"]
    if kind == "mqtt":
        body = [
            f"  servers = [{_quote(source['endpoint'])}]",
            f"  topics = [{', '.join(_quote(topic) for topic in options['topics'])}]",
            f"  qos = {int(options['qos'])}",
            f"  client_id = {_quote('plantcraft-historian-' + source['id'])}",
            f"  data_format = {_quote(options['data_format'])}",
        ]
        if options["data_format"] == "value":
            body.append('  data_type = "float"')
        if source.get("username"):
            body.append(f"  username = {_quote(source['username'])}")
        if password:
            body.append(f"  password = {_quote(password)}")
        return [*head, *body, *tags]
    if kind == "modbus":
        body = [
            f"  name = {_quote(source['id'])}",
            f"  interval = {_quote(_duration(scan))}",
            f"  controller = {_quote(source['endpoint'])}",
            f"  slave_id = {int(options['slave_id'])}",
            f"  timeout = {_quote(_duration(options['timeout_seconds']))}",
            '  configuration_type = "register"',
        ]
        for register_type, table in REGISTER_TABLES.items():
            entries = [item for item in options["registers"] if item["type"] == register_type]
            if not entries:
                continue
            body.append(f"  {table} = [")
            for item in entries:
                body.append(f"    {{ {_register(item)} }},")
            body.append("  ]")
        return [*head, *body, *tags]
    dsn = source["endpoint"].replace("{password}", password)
    query = [
        "  [[inputs.sql.query]]",
        f"    query = {_quote(options['query'])}",
        f"    measurement = {_quote(options['measurement'])}",
    ]
    if options["time_column"]:
        query.append(f"    time_column = {_quote(options['time_column'])}")
    if options["tag_columns"]:
        columns = ", ".join(_quote(column) for column in options["tag_columns"])
        query.append(f"    tag_columns_include = [{columns}]")
    # Telegraf would also send the time and tag columns as fields: a "time" and a "tag" point
    # beside each value (found by the source test kit, 2026-10-24).
    kept_out = [column for column in [options["time_column"], *options["tag_columns"]] if column]
    if kept_out:
        columns = ", ".join(_quote(column) for column in kept_out)
        query.append(f"    field_columns_exclude = [{columns}]")
    body = [
        f"  interval = {_quote(_duration(scan))}",
        f"  driver = {_quote(SQL_DRIVERS[options['driver']])}",
        f"  dsn = {_quote(dsn)}",
    ]
    # The source's tag first: after [[inputs.sql.query]] a table would belong to the query.
    return [*head, *body, *tags, *query]


def _scaled_type(data_type: str, scale: float) -> str:
    """An integer register with a fractional scale (0.1) as Telegraf's fixed point type: an
    INT16 times 0.1 would come out as an integer, 552 x 0.1 = 55 (source test kit, 2026-10-24)."""

    if scale.is_integer() or data_type.startswith(("FLOAT", "FIXED", "UFIXED")):
        return data_type
    if data_type in ("INT8L", "INT8H", "UINT8L", "UINT8H"):
        return data_type  # one byte of a register: no fixed point form
    return "UFIXED" if data_type.startswith("U") else "FIXED"


def _register(item: dict[str, Any]) -> str:
    parts = [f"name = {_quote(item['name'])}"]
    if item["type"] in ("holding_register", "input_register"):
        order = byte_order_of(item["data_type"], item["byte_order"])
        words = register_words(item["data_type"], order)
        parts += [
            f"byte_order = {_quote(order)}",
            f"data_type = {_quote(_scaled_type(item['data_type'], float(item['scale'])))}",
            f"scale = {float(item['scale'])!r}",
        ]
        addresses = list(range(item["address"], item["address"] + words))
    else:
        addresses = [item["address"]]
    parts.append(f"address = [{', '.join(str(address) for address in addresses)}]")
    return ", ".join(parts)


def write_config(
    settings: Settings,
    sources: list[dict[str, Any]],
    password: Callable[[dict[str, Any]], str],
    previous: str,
    general_scan: float = 10.0,
) -> str:
    """Write the configuration when it changed; the text written."""

    text = render(settings, sources, password, general_scan)
    path = Path(settings.data_dir) / FOLDER / CONFIG
    if text != previous or not path.exists():
        _private(path, text)
    return text


def variable(kind: str, address: str, seen: dict[str, Any]) -> dict[str, Any]:
    """A series the gateway sent, as Browse lists it (``collector.opcua`` lists the same)."""

    tags: dict[str, str] = seen.get("tags") or {}
    field = str(seen.get("field") or "")
    if kind == "mqtt":
        tag = tags.get("topic", seen.get("measurement", "")).strip("/").replace("/", ".")
        tag = tag if field == "value" else f"{tag}.{field}"
    elif kind == "modbus":
        tag = field
    else:
        tag = ".".join([*(value for _, value in sorted(tags.items())), field])
    value = seen.get("value")
    text = isinstance(value, str)
    return {
        "address": address,
        "tag": tag or address,
        "name": field,
        "path": address,
        "kind": "text" if text else "number",
        "step": isinstance(value, bool) or text,
        "unit": "",
        "description": "",
        "low": None,
        "high": None,
        "value": value,
    }
