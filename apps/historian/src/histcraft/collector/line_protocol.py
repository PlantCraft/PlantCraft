"""InfluxDB line protocol, the format Telegraf writes (``outputs.influxdb_v2``).

One line per metric: ``measurement[,tag=value...] field=value[,field=value...] [timestamp]``.
Backslash escapes a comma or space in the measurement; a comma, ``=`` or space in tag keys,
tag values and field keys; a double quote or backslash inside a string field. A field value is
a float (``1.5``, ``-2e3``), an integer (``7i``), an unsigned integer (``7u``), a boolean
(``t``, ``true``, ``F``...) or a string (``"AUTO"``). The timestamp counts ``precision`` units
since 1970 (nanoseconds by default); without one the metric is stamped when it is received.

A point's address on a Telegraf source is the metric's series key and field, written the way
line protocol writes them: ``modbus,name=PLC1,type=holding_register FT-101`` (tags sorted).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

PRECISIONS = {"ns": 1_000_000, "us": 1_000, "ms": 1, "s": 1 / 1000}
_TRUE = {"t", "T", "true", "True", "TRUE"}
_FALSE = {"f", "F", "false", "False", "FALSE"}
MAX_LINE = 64 * 1024


class LineError(ValueError):
    """A line that is not line protocol; the message says where."""


@dataclass
class Metric:
    measurement: str
    tags: dict[str, str]
    fields: dict[str, Any]
    # Milliseconds since 1970, or None for "when received".
    at_ms: int | None

    def series(self) -> str:
        """The series key (measurement and sorted tags), escaped as line protocol."""

        parts = [_escape(self.measurement, ", ")]
        parts += [
            f"{escape_key(key)}={escape_key(value)}" for key, value in sorted(self.tags.items())
        ]
        return ",".join(parts)

    def addresses(self) -> dict[str, Any]:
        """Each field's address (``<series> <field>``) and value."""

        series = self.series()
        return {f"{series} {escape_key(key)}": value for key, value in self.fields.items()}


def address(measurement: str, tags: dict[str, str], field: str) -> str:
    return f"{Metric(measurement, tags, {}, None).series()} {escape_key(field)}"


def escape_key(text: str) -> str:
    """A tag key or value, or a field key, escaped as line protocol."""

    return _escape(text, ",= ")


def _escape(text: str, special: str) -> str:
    out = text.replace("\\", "\\\\") if "\\" in text else text
    for char in special:
        out = out.replace(char, "\\" + char)
    return out


def parse(text: str, precision: str = "ns") -> tuple[list[Metric], list[str]]:
    """The metrics in ``text`` and an error per line that could not be read."""

    if precision not in PRECISIONS:
        raise LineError(f"unknown precision {precision}")
    metrics: list[Metric] = []
    errors: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            metrics.append(parse_line(line, precision))
        except LineError as exc:
            errors.append(f"line {number}: {exc}")
    return metrics, errors


def parse_line(line: str, precision: str = "ns") -> Metric:
    if len(line) > MAX_LINE:
        raise LineError("line too long")
    position = 0
    measurement, position = _token(line, position, stops=", ")
    if not measurement:
        raise LineError("no measurement")
    tags: dict[str, str] = {}
    while position < len(line) and line[position] == ",":
        key, position = _token(line, position + 1, stops="=")
        if position >= len(line) or not key:
            raise LineError("a tag without =")
        value, position = _token(line, position + 1, stops=", ")
        if not value:
            raise LineError(f"tag {key} has no value")
        tags[key] = value
    if position >= len(line) or line[position] != " ":
        raise LineError("no fields")
    position = _spaces(line, position)
    fields: dict[str, Any] = {}
    while True:
        key, position = _token(line, position, stops="=")
        if position >= len(line) or not key:
            raise LineError("a field without =")
        value, position = _field_value(line, position + 1)
        fields[key] = value
        if position < len(line) and line[position] == ",":
            position += 1
            continue
        break
    at_ms = None
    if position < len(line):
        if line[position] != " ":
            raise LineError(f"unexpected {line[position]!r}")
        stamp = line[_spaces(line, position) :].strip()
        if stamp:
            try:
                at_ms = int(int(stamp) / PRECISIONS[precision])
            except ValueError:
                raise LineError(f"timestamp {stamp!r} is not an integer") from None
    return Metric(measurement, tags, fields, at_ms)


def _spaces(line: str, position: int) -> int:
    while position < len(line) and line[position] == " ":
        position += 1
    return position


def _token(line: str, position: int, *, stops: str) -> tuple[str, int]:
    out: list[str] = []
    while position < len(line):
        char = line[position]
        if char == "\\" and position + 1 < len(line):
            following = line[position + 1]
            if following in stops or following in ",= \\":
                out.append(following)
                position += 2
                continue
        if char in stops:
            break
        out.append(char)
        position += 1
    return "".join(out), position


def _field_value(line: str, position: int) -> tuple[Any, int]:
    if position < len(line) and line[position] == '"':
        out: list[str] = []
        position += 1
        while position < len(line):
            char = line[position]
            if char == "\\" and position + 1 < len(line) and line[position + 1] in '"\\':
                out.append(line[position + 1])
                position += 2
                continue
            if char == '"':
                return "".join(out), position + 1
            out.append(char)
            position += 1
        raise LineError("a string field is not closed")
    end = position
    while end < len(line) and line[end] not in ", ":
        end += 1
    raw = line[position:end]
    if not raw:
        raise LineError("a field without a value")
    if raw in _TRUE:
        return True, end
    if raw in _FALSE:
        return False, end
    try:
        if raw[-1] in "iu":
            return int(raw[:-1]), end
        value = float(raw)
    except ValueError:
        raise LineError(f"field value {raw!r} is not a number, boolean or string") from None
    if not math.isfinite(value):
        raise LineError(f"field value {raw!r} is not finite")
    return value, end
