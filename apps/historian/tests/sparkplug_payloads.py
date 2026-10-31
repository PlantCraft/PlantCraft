"""Sparkplug B payloads, encoded (the protobuf wire format of the public sparkplug_b.proto)."""

from __future__ import annotations

import struct
from typing import Any

INT64_TYPES = (4, 8, 13)  # Int64, UInt64, DateTime: long_value
INT32_TYPES = (1, 2, 3, 5, 6, 7)  # int_value, two's complement for the signed ones
TEXT_TYPES = (12, 14, 15)


def _varint(number: int) -> bytes:
    out = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(number: int, wire: int) -> bytes:
    return _varint(number << 3 | wire)


def _bytes(number: int, data: bytes) -> bytes:
    return _key(number, 2) + _varint(len(data)) + data


def _uint(number: int, value: int) -> bytes:
    return _key(number, 0) + _varint(value)


def _property(value: Any) -> bytes:
    if isinstance(value, bool):
        return _uint(1, 11) + _uint(7, int(value))
    if isinstance(value, int):
        return _uint(1, 3) + _uint(3, value & 0xFFFFFFFF)
    if isinstance(value, float):
        return _uint(1, 10) + _key(6, 1) + struct.pack("<d", value)
    return _uint(1, 12) + _bytes(8, str(value).encode())


def properties(values: dict[str, Any]) -> bytes:
    out = b"".join(_bytes(1, key.encode()) for key in values)
    return out + b"".join(_bytes(2, _property(value)) for value in values.values())


def metric(
    name: str | None = None,
    value: Any = None,
    datatype: int | None = 10,
    *,
    alias: int | None = None,
    timestamp: int | None = None,
    props: dict[str, Any] | None = None,
    members: list[bytes] | None = None,
    definition: bool = False,
) -> bytes:
    out = b""
    if name is not None:
        out += _bytes(1, name.encode())
    if alias is not None:
        out += _uint(2, alias)
    if timestamp is not None:
        out += _uint(3, timestamp)
    if datatype:
        out += _uint(4, datatype)
    if props:
        out += _bytes(9, properties(props))
    if members is not None:
        template = b"".join(_bytes(2, member) for member in members)
        return out + _bytes(18, template + _uint(5, int(definition)))
    if value is None:
        return out + _uint(7, 1)
    if datatype == 11 or isinstance(value, bool):
        return out + _uint(14, int(value))
    if datatype in INT32_TYPES:
        return out + _uint(10, value & 0xFFFFFFFF)
    if datatype in INT64_TYPES:
        return out + _uint(11, value & 0xFFFFFFFFFFFFFFFF)
    if datatype == 9:
        return out + _key(12, 5) + struct.pack("<f", value)
    if datatype in TEXT_TYPES or isinstance(value, str):
        return out + _bytes(15, str(value).encode())
    return out + _key(13, 1) + struct.pack("<d", float(value))


def payload(metrics: list[bytes], *, seq: int | None = None, timestamp: int | None = None) -> bytes:
    out = b"" if timestamp is None else _uint(1, timestamp)
    out += b"".join(_bytes(2, item) for item in metrics)
    return out + (b"" if seq is None else _uint(3, seq))
