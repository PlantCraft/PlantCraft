"""Chunks of archived values as compact bytes.

A chunk holds the archived values of one point, in time order. Times are
integer milliseconds since the Unix epoch (UTC), stored as differences;
numbers are floats (NaN marks "no data": a gap that reads never bridge);
text and structured values are a JSON list of labels (``null`` marks a gap).

Layout: one byte version and kind, then a compressed body.

- ``0x20`` numbers, ``0x21`` text (Historian 0.5): a zstd frame. The body of numbers is
  ``uint8 flags``, ``uint32 count``, ``int64 first time``, the differences and the values, each
  byte-shuffled (the first byte of every item, then the second...): neighbouring values share
  their high bytes, which then sit side by side for the compressor. Differences are int32 when
  they fit (flag 1), values float32 when every value is one exactly (flag 2: a PLC's REAL, a
  digital state), else int64 and float64. Typical cost: 3 to 4 bytes per value, encoded about
  5 times faster than the zlib layout. Text is ``uint32 count``, ``int64 first time``, int64
  differences and the JSON labels.
- ``0x10`` numbers, ``0x11`` text (Historian 0.4 and earlier): a zlib stream of ``uint32
  count``, ``int64 first time``, ``int64[count-1]`` differences and the float64 values or the
  labels. Still read; rewritten in the new layout whenever a chunk is (compaction, a merge).

``encode_batch`` / ``decode_batch`` hold many points' values in one blob: the recent values
the collector writes every few seconds (``ArchiveStore.hold``).
"""

from __future__ import annotations

import json
import struct
import threading
import zlib
from collections.abc import Sequence
from typing import Any

import numpy as np

from histcraft.kinds import labelled

try:  # Python 3.14 has zstd in the standard library; before it, the zstandard wheel.
    from compression import zstd as _zstd_std  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on the Python version
    _zstd_std = None
    import zstandard as _zstandard

NUMBER, TEXT = 0x20, 0x21
ZLIB_NUMBER, ZLIB_TEXT = 0x10, 0x11
BATCH = 0x30
_KNOWN = (NUMBER, TEXT, ZLIB_NUMBER, ZLIB_TEXT)
_HEAD = struct.Struct("<Iq")
_FLAGS = struct.Struct("<B")
_SMALL_DELTAS, _FLOAT32 = 1, 2
# zstd level of chunks: 3 is zstd's default; higher levels gain little on shuffled floats.
LEVEL = 3
_I32 = np.iinfo(np.int32)
_local = threading.local()


class CodecError(ValueError):
    """Bytes that are not a chunk this version wrote."""


def _compress(data: bytes, level: int = LEVEL) -> bytes:
    if _zstd_std is not None:  # pragma: no cover - Python 3.14+
        return _zstd_std.compress(data, level)
    # Compressor objects are not safe across threads: one per thread and level.
    compressors = getattr(_local, "compressors", None)
    if compressors is None:
        compressors = _local.compressors = {}
    compressor = compressors.get(level)
    if compressor is None:
        compressor = compressors[level] = _zstandard.ZstdCompressor(level=level)
    return compressor.compress(data)


def _decompress(data: bytes) -> bytes:
    if _zstd_std is not None:  # pragma: no cover - Python 3.14+
        return _zstd_std.decompress(data)
    decompressor = getattr(_local, "decompressor", None)
    if decompressor is None:
        decompressor = _local.decompressor = _zstandard.ZstdDecompressor()
    return decompressor.decompress(data)


def _shuffle(array: np.ndarray) -> bytes:
    width = array.dtype.itemsize
    return np.frombuffer(array.tobytes(), dtype=np.uint8).reshape(-1, width).T.tobytes()


def _unshuffle(body: bytes, offset: int, count: int, dtype: str) -> np.ndarray:
    width = np.dtype(dtype).itemsize
    raw = np.frombuffer(body, dtype=np.uint8, count=count * width, offset=offset)
    return raw.reshape(width, count).T.copy().view(dtype).reshape(count)


def _check(times: np.ndarray, count: int) -> None:
    if len(times) != count or not len(times):
        raise CodecError("a chunk needs as many times as values, at least one")


def encode_numbers(times_ms: np.ndarray, values: np.ndarray) -> bytes:
    times = np.asarray(times_ms, dtype="<i8")
    numbers = np.asarray(values, dtype="<f8")
    _check(times, len(numbers))
    deltas = np.diff(times)
    flags = 0
    if not len(deltas) or (deltas.min() >= _I32.min and deltas.max() <= _I32.max):
        flags |= _SMALL_DELTAS
        deltas = deltas.astype("<i4")
    with np.errstate(over="ignore", invalid="ignore"):  # too large for float32: kept float64
        single = numbers.astype("<f4")
    if np.array_equal(single.astype("<f8"), numbers, equal_nan=True):
        flags |= _FLOAT32
        numbers = single
    body = (
        _FLAGS.pack(flags)
        + _HEAD.pack(len(times), int(times[0]))
        + _shuffle(deltas)
        + _shuffle(numbers)
    )
    return bytes([NUMBER]) + _compress(body)


def encode_text(times_ms: np.ndarray, labels: Sequence[str | None]) -> bytes:
    times = np.asarray(times_ms, dtype="<i8")
    _check(times, len(labels))
    text = json.dumps(list(labels), ensure_ascii=False, separators=(",", ":")).encode()
    body = _HEAD.pack(len(times), int(times[0])) + np.diff(times).tobytes() + text
    return bytes([TEXT]) + _compress(body)


def _times(first: int, deltas: np.ndarray, count: int) -> np.ndarray:
    times = np.empty(count, dtype=np.int64)
    times[0] = first
    np.cumsum(deltas, out=times[1:], dtype=np.int64)
    times[1:] += first
    return times


def decode(blob: bytes) -> tuple[np.ndarray, np.ndarray | list[str | None]]:
    """``(times_ms, values)``: values are a float array, or a list of labels for text."""

    if not blob or blob[0] not in _KNOWN:
        raise CodecError("unknown chunk format")
    version = blob[0]
    try:
        if version in (NUMBER, TEXT):
            body = _decompress(blob[1:])
        else:
            body = zlib.decompress(blob[1:])
        flags = 0
        offset = 0
        if version == NUMBER:
            (flags,) = _FLAGS.unpack_from(body)
            offset = _FLAGS.size
        count, first = _HEAD.unpack_from(body, offset)
        offset += _HEAD.size
        if version == NUMBER:
            delta_type = "<i4" if flags & _SMALL_DELTAS else "<i8"
            value_type = "<f4" if flags & _FLOAT32 else "<f8"
            deltas = _unshuffle(body, offset, count - 1, delta_type)
            offset += np.dtype(delta_type).itemsize * (count - 1)
            values = _unshuffle(body, offset, count, value_type).astype(np.float64)
            return _times(first, deltas, count), values
        deltas = np.frombuffer(body, dtype="<i8", count=count - 1, offset=offset)
        offset += 8 * (count - 1)
        times = _times(first, deltas, count)
        if version == ZLIB_NUMBER:
            values = np.frombuffer(body, dtype="<f8", count=count, offset=offset).astype(np.float64)
            return times, values
        labels = json.loads(body[offset:].decode())
    except CodecError:
        raise
    except Exception as exc:  # zlib, zstd, struct and numpy each raise their own
        raise CodecError(f"damaged chunk: {exc}") from exc
    if len(labels) != count:
        raise CodecError("damaged chunk: label count")
    return times, labels


def encode(times_ms: np.ndarray, values: np.ndarray | Sequence[str | None], kind: str) -> bytes:
    if labelled(kind):
        return encode_text(times_ms, list(values))
    return encode_numbers(times_ms, np.asarray(values, dtype=float))


# Many points in one blob (the recent values) -----------------------------------------------

_BATCH_HEAD = struct.Struct("<II")


def encode_batch(batch: dict[int, tuple[str, list[tuple[int, Any]]]]) -> bytes:
    """``{point: (kind, [(ms, value), ...])}`` as one blob: number points as three arrays
    (point, time, value), labelled points as JSON. Fast to write and to read (zstd level 1)."""

    numbers: list[tuple[int, list[tuple[int, Any]]]] = []
    labels: dict[str, list[Any]] = {}
    for point, (kind, samples) in batch.items():
        if not samples:
            continue
        if labelled(kind):
            labels[str(point)] = [kind, [at for at, _ in samples], [v for _, v in samples]]
        else:
            numbers.append((point, samples))
    count = sum(len(samples) for _, samples in numbers)
    points = np.empty(count, dtype="<i8")
    times = np.empty(count, dtype="<i8")
    values = np.empty(count, dtype="<f8")
    at = 0
    for point, samples in numbers:
        size = len(samples)
        points[at : at + size] = point
        times[at : at + size] = [moment for moment, _ in samples]
        values[at : at + size] = [_float(value) for _, value in samples]
        at += size
    text = json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode() if labels else b""
    body = (
        _BATCH_HEAD.pack(count, len(text))
        + points.tobytes()
        + times.tobytes()
        + values.tobytes()
        + text
    )
    return bytes([BATCH]) + _compress(body, 1)


def decode_batch_arrays(
    blob: bytes,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[int, tuple[str, np.ndarray, list[Any]]]]:
    """An ``encode_batch`` blob as it is stored: number points as ``(points, times, values)``
    arrays (each point's values together, in time order), labelled points by point."""

    if not blob or blob[0] != BATCH:
        raise CodecError("unknown batch format")
    try:
        body = _decompress(blob[1:])
        count, size = _BATCH_HEAD.unpack_from(body)
        offset = _BATCH_HEAD.size
        points = np.frombuffer(body, dtype="<i8", count=count, offset=offset)
        times = np.frombuffer(body, dtype="<i8", count=count, offset=offset + 8 * count)
        values = np.frombuffer(body, dtype="<f8", count=count, offset=offset + 16 * count)
        text = json.loads(body[offset + 24 * count :].decode()) if size else {}
        labels = {
            int(point): (str(kind), np.asarray(stamps, dtype=np.int64), list(found))
            for point, (kind, stamps, found) in text.items()
        }
    except Exception as exc:
        raise CodecError(f"damaged batch: {exc}") from exc
    return points, times, values, labels


def decode_batch(blob: bytes) -> dict[int, tuple[str, np.ndarray, Any]]:
    """``{point: (kind, times ms, values)}`` of an ``encode_batch`` blob (numbers as floats)."""

    points, times, values, labels = decode_batch_arrays(blob)
    out: dict[int, tuple[str, np.ndarray, Any]] = {}
    for point, start, end in point_runs(points):
        out[point] = ("number", times[start:end], values[start:end])
    out.update(labels)
    return out


def point_runs(points: np.ndarray) -> list[tuple[int, int, int]]:
    """``(point, start, end)`` of each run of equal ``points``."""

    if not len(points):
        return []
    cuts = np.flatnonzero(points[1:] != points[:-1]) + 1
    starts = np.concatenate([[0], cuts]).tolist()
    ends = np.concatenate([cuts, [len(points)]]).tolist()
    return [(int(points[a]), a, b) for a, b in zip(starts, ends, strict=True)]


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
