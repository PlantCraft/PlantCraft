"""The binary answer of ``POST /api/v1/series``: times and values as arrays, not text.

A raw day of 200 fast signals is millions of values. As JSON each one is an ISO time text and a
number text, written by the Historian and parsed again by the app: most of a round's read
(2026-10-31 bench: 200 signals x 24 h, 7 million values, 19 s, of which the database 0.6 s).
This format writes the arrays the Historian already holds, as they are, and the SDK reads them
straight into numpy and pandas: no text, no per-value Python object.

A client asks for it with ``Accept: application/x-plantcraft-series`` on ``POST /api/v1/series``
(a Historian that serves it says so in ``GET /api/v1/reads``: ``"formats"``). The JSON answer
stays the default and holds the same series, errors and order.

Layout (little-endian)::

    b"PCS1"  uint32 header length  header (UTF-8 JSON)  zero padding to 8 bytes
    then, for each series of the header with ``"n"``: int64[n] times (ms since 1970, UTC),
    float64[n] values (NaN where JSON has null)

The header is ``{"series": [{"signal", "kind", "n", ...extra}], "errors": [...]}``; a series
whose values are not numbers (text, labels, structured) carries them in the header as ``"t"``
(ms) and ``"v"``, as JSON would, and has no ``"n"``.
"""

from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np
import pandas as pd

MEDIA_TYPE = "application/x-plantcraft-series"
MAGIC = b"PCS1"
FORMAT = "pcs1"


class WireError(ValueError):
    """The bytes are not a binary series answer this SDK can read."""


def _pad(size: int) -> int:
    return (-size) % 8


class BinaryWriter:
    """Builds one binary answer, series by series (the Historian's side)."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.buffers: list[bytes] = []

    def numbers(
        self,
        signal: str,
        kind: str,
        times_ms: np.ndarray,
        values: np.ndarray,
        extra: dict[str, Any] | None = None,
    ) -> int:
        times = np.ascontiguousarray(times_ms, dtype="<i8")
        floats = np.ascontiguousarray(values, dtype="<f8")
        if len(times) != len(floats):
            raise ValueError("times and values differ in length")
        self.items.append({"signal": signal, "kind": kind, "n": len(times), **(extra or {})})
        self.buffers += [times.tobytes(), floats.tobytes()]
        return len(times)

    def labels(
        self,
        signal: str,
        kind: str,
        times_ms: np.ndarray,
        values: list[Any],
        extra: dict[str, Any] | None = None,
    ) -> int:
        stamps = np.asarray(times_ms, dtype=np.int64).tolist()
        self.items.append(
            {"signal": signal, "kind": kind, "t": stamps, "v": list(values), **(extra or {})}
        )
        return len(stamps)

    def body(self, errors: list[dict[str, Any]]) -> bytes:
        header = json.dumps(
            {"series": self.items, "errors": errors}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        start = MAGIC + struct.pack("<I", len(header)) + header
        return b"".join([start, b"\0" * _pad(len(start)), *self.buffers])


def read_binary(body: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(series, errors)`` of a binary answer; each series' ``t`` is int64 ms, ``v`` float64
    (numbers) or a list (labels): numpy arrays that share the answer's memory, read-only."""

    view = memoryview(body)
    if len(view) < 8 or bytes(view[:4]) != MAGIC:
        raise WireError("Not a PCS1 series answer.")
    (size,) = struct.unpack("<I", view[4:8])
    end = 8 + size
    if end > len(view):
        raise WireError("Truncated PCS1 header.")
    header = json.loads(bytes(view[8:end]))
    offset = end + _pad(end)
    series: list[dict[str, Any]] = []
    for item in header.get("series") or []:
        count = item.pop("n", None)
        if count is None:
            item["t"] = np.asarray(item.get("t") or [], dtype=np.int64)
            series.append(item)
            continue
        count = int(count)
        need = offset + 16 * count
        if need > len(view):
            raise WireError("Truncated PCS1 arrays.")
        item["t"] = np.frombuffer(view, dtype="<i8", count=count, offset=offset)
        item["v"] = np.frombuffer(view, dtype="<f8", count=count, offset=offset + 8 * count)
        offset = need
        series.append(item)
    return series, list(header.get("errors") or [])


def binary_to_pandas(item: dict[str, Any]) -> pd.Series:
    """One series of ``read_binary`` as ``series_to_pandas`` gives it: a UTC DatetimeIndex, floats
    (NaN for null) for a number, labels (object) for text."""

    index = (
        pd.DatetimeIndex(np.asarray(item["t"], dtype=np.int64).astype("datetime64[ms]"))
        .tz_localize("UTC")
        .as_unit("ns")
    )
    values = item.get("v")
    if item.get("kind") == "text":
        return pd.Series(list(values or []), index=index, name=item.get("signal"), dtype=object)
    if isinstance(values, np.ndarray):
        return pd.Series(values, index=index, name=item.get("signal"), dtype=float, copy=False)
    numbers = np.array([np.nan if v is None else v for v in values or []], dtype=float)
    return pd.Series(numbers, index=index, name=item.get("signal"), dtype=float)


__all__ = ["FORMAT", "MEDIA_TYPE", "BinaryWriter", "WireError", "binary_to_pandas", "read_binary"]
