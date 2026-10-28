"""Plain data to and from JSON for the suite's compute workers (docs/compute.md in PlantCraft).

A compute task crosses to another container, maybe another machine, so it carries no pickle:
only JSON, which reads nothing but data. ``encode`` turns what the analyses pass around (pandas
frames and series, numpy arrays, timestamps, ``Result`` and ``NoData``, floats that are not
numbers) into JSON values, and ``decode`` turns them back. Numbers travel as their exact bytes
(base64), so a frame comes back with the same values and types. A tagged value is a dict with one
key that starts with ``$``; a dict of the data that has such keys travels as ``$dict``.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import math
from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import NoData, Result

_DATACLASSES: dict[str, type] = {"Result": Result, "NoData": NoData}
_NUMERIC = "biuf"


class WireError(TypeError):
    """A value that cannot cross to a compute worker."""


def _bytes(array: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(array).tobytes()).decode("ascii")


def _array(values: Any) -> dict[str, Any]:  # noqa: ANN401
    """The values of a column, an index or an array (one dimension)."""

    if isinstance(values, pd.arrays.NumpyExtensionArray) or (
        isinstance(values, pd.api.extensions.ExtensionArray)
        and not isinstance(values.dtype, pd.api.extensions.ExtensionDtype)
    ):
        # What ``.array`` gives for plain numpy data (numbers, a naive time index): its bytes,
        # not value by value.
        values = values.to_numpy()
    if isinstance(values, (pd.api.extensions.ExtensionArray, pd.Categorical)) or (
        hasattr(values, "dtype") and isinstance(values.dtype, pd.api.extensions.ExtensionDtype)
    ):
        if isinstance(values.dtype, pd.DatetimeTZDtype):
            return {
                "dtype": f"<M8[{values.dtype.unit}]",
                "tz": str(values.dtype.tz),
                "b64": _bytes(np.asarray(values.asi8, dtype="<i8")),
            }
        # Nullable and categorical types: their values one by one, then the type again.
        return {"dtype": str(values.dtype), "list": [encode(item) for item in values.tolist()]}
    array = np.asarray(values)
    if array.dtype.kind in _NUMERIC:
        array = array.astype(array.dtype.newbyteorder("<"), copy=False)
        return {"dtype": array.dtype.str, "b64": _bytes(array)}
    if array.dtype.kind in "mM":
        unit = np.datetime_data(array.dtype)[0]
        return {
            "dtype": array.dtype.str,
            "b64": _bytes(array.astype(f"<{array.dtype.kind.lower()}8[{unit}]").view("<i8")),
        }
    return {"dtype": "object", "list": [encode(item) for item in array.tolist()]}


def _unarray(data: dict[str, Any]) -> Any:  # noqa: ANN401
    dtype = data.get("dtype", "object")
    if "b64" in data:
        raw = base64.b64decode(data["b64"])
        if dtype.lstrip("<>|=").startswith(("M8", "m8")):
            array = np.frombuffer(raw, dtype="<i8").view(np.dtype(dtype))
        else:
            array = np.frombuffer(raw, dtype=np.dtype(dtype))
        array = array.copy()  # writable, like the original
        if data.get("tz"):
            return pd.DatetimeIndex(array).tz_localize("UTC").tz_convert(data["tz"]).array
        return array
    values = [decode(item) for item in data.get("list", [])]
    if dtype == "object":
        array = np.empty(len(values), dtype=object)
        array[:] = values
        return array
    return pd.array(values, dtype=dtype)


def _index(index: pd.Index) -> dict[str, Any]:
    return {"values": _array(index.array), "name": encode(index.name)}


def _unindex(data: dict[str, Any]) -> pd.Index:
    values = _unarray(data["values"])
    return pd.Index(values, name=decode(data.get("name")))


def encode(value: Any) -> Any:  # noqa: ANN401, PLR0911, PLR0912
    """``value`` as JSON values (raises ``WireError`` for what cannot cross)."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, np.integer)) and not isinstance(value, np.bool_):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isfinite(number):
            return number
        return {"$f": "nan" if math.isnan(number) else ("inf" if number > 0 else "-inf")}
    if value is pd.NaT:
        return {"$nat": True}
    if value is pd.NA:
        return {"$na": True}
    if isinstance(value, pd.Timestamp):
        return {"$ts": value.isoformat()}
    if isinstance(value, dt.datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, dt.date):
        return {"$date": value.isoformat()}
    if isinstance(value, (pd.Timedelta, dt.timedelta, np.timedelta64)):
        return {"$td": pd.Timedelta(value).value}
    if isinstance(value, np.datetime64):
        return {"$ts": pd.Timestamp(value).isoformat()}
    if isinstance(value, pd.DataFrame):
        return {
            "$frame": {
                "index": _index(value.index),
                "columns": _index(value.columns),
                "data": [_array(value.iloc[:, number].array) for number in range(value.shape[1])],
                "attrs": encode(dict(value.attrs)),
            }
        }
    if isinstance(value, pd.Series):
        return {
            "$series": {
                "index": _index(value.index),
                "name": encode(value.name),
                "values": _array(value.array),
                "attrs": encode(dict(value.attrs)),
            }
        }
    if isinstance(value, pd.Index):
        return {"$index": _index(value)}
    if isinstance(value, np.ndarray):
        if value.ndim != 1:
            return {"$nd": {"shape": list(value.shape), "values": _array(value.reshape(-1))}}
        return {"$nd": {"shape": [len(value)], "values": _array(value)}}
    if isinstance(value, pd.api.extensions.ExtensionArray):
        return {"$array": _array(value)}
    if dataclasses.is_dataclass(value) and type(value).__name__ in _DATACLASSES:
        fields = {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
        return {"$" + type(value).__name__: encode(fields)}
    if isinstance(value, dict):
        if all(isinstance(key, str) and not key.startswith("$") for key in value):
            return {key: encode(item) for key, item in value.items()}
        return {"$dict": [[encode(key), encode(item)] for key, item in value.items()]}
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, tuple):
        return {"$tuple": [encode(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        return {"$set": [encode(item) for item in value]}
    raise WireError(f"a {type(value).__name__} cannot go to a compute worker")


def _decode_tagged(tag: str, body: Any) -> Any:  # noqa: ANN401, PLR0911
    if tag == "$f":
        return {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}[body]
    if tag == "$nat":
        return pd.NaT
    if tag == "$na":
        return pd.NA
    if tag == "$ts":
        return pd.Timestamp(body)
    if tag == "$dt":
        return dt.datetime.fromisoformat(body)
    if tag == "$date":
        return dt.date.fromisoformat(body)
    if tag == "$td":
        return pd.Timedelta(int(body))
    if tag == "$frame":
        index = _unindex(body["index"])
        frame = pd.DataFrame(
            {number: _unarray(column) for number, column in enumerate(body["data"])},
            index=index,
        )
        frame.columns = _unindex(body["columns"])
        frame.attrs.update(decode(body.get("attrs") or {}))
        return frame
    if tag == "$series":
        series = pd.Series(
            _unarray(body["values"]), index=_unindex(body["index"]), name=decode(body.get("name"))
        )
        series.attrs.update(decode(body.get("attrs") or {}))
        return series
    if tag == "$index":
        return _unindex(body)
    if tag == "$nd":
        return np.asarray(_unarray(body["values"])).reshape(body["shape"])
    if tag == "$array":
        return _unarray(body)
    if tag == "$dict":
        return {decode(key): decode(item) for key, item in body}
    if tag == "$tuple":
        return tuple(decode(item) for item in body)
    if tag == "$set":
        return {decode(item) for item in body}
    kind = _DATACLASSES.get(tag[1:])
    if kind is not None:
        return kind(**decode(body))
    raise WireError(f"unknown value {tag} from a compute worker")


def decode(value: Any) -> Any:  # noqa: ANN401
    """The value ``encode`` wrote."""

    if isinstance(value, list):
        return [decode(item) for item in value]
    if isinstance(value, dict):
        if len(value) == 1:
            ((key, body),) = value.items()
            if key.startswith("$"):
                return _decode_tagged(key, body)
        return {key: decode(item) for key, item in value.items()}
    return value


__all__ = ["WireError", "decode", "encode"]
