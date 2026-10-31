"""A simulation's results: the variables (from ``model_init.xml``) and their values (the CSV).

The CSV omc writes is turned once into a compact matrix (``values.npy``, one column per
variable, time first) and a list of names, so a plot reads only the columns it shows. Plots
get at most ``max_points`` points per variable: each bucket keeps its first, smallest and
largest value, so a spike never disappears from the chart.
"""

from __future__ import annotations

import csv
import json
import math
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

import numpy as np
from plantcraft_sdk.files import write_json

MAX_VARIABLES = 20_000
MAX_ROWS = 400_000
VALUES = "values.npy"
NAMES = "names.json"
VARIABLES = "variables.json"


def variables_from_init(path: Path | None) -> list[dict[str, Any]]:
    """Every variable the model declares, with its description, unit, kind and start value."""

    if path is None or not path.is_file():
        return []
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return []
    found = []
    for item in root.iter("ScalarVariable"):
        name = item.get("name", "")
        if not name:
            continue
        typed = next(iter(item), None)
        start = typed.get("start") if typed is not None else None
        variability = item.get("variability", "")
        causality = item.get("causality", "")
        kind = (
            "parameter"
            if causality == "parameter" or variability == "parameter"
            else "input"
            if causality == "input"
            else "output"
            if causality == "output"
            else "state"
            if item.get("classType") == "rSta"
            else "derivative"
            if item.get("classType") == "rDer"
            else "variable"
        )
        found.append(
            {
                "name": name,
                "description": item.get("description", ""),
                "unit": (typed.get("unit") or typed.get("displayUnit") or "")
                if typed is not None
                else "",
                "type": typed.tag if typed is not None else "",
                "kind": kind,
                "start": start,
                "changeable": item.get("isValueChangeable") == "true",
                "protected": item.get("isProtected") == "true",
                "alias": item.get("alias", "noAlias") != "noAlias",
            }
        )
        if len(found) >= MAX_VARIABLES:
            break
    return found


def _number(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        return math.nan
    return value if math.isfinite(value) else math.nan


def store(csv_path: Path, init_path: Path | None, folder: Path) -> dict[str, Any]:
    """Turn omc's CSV into the run's matrix; ``{"variables", "rows", "start", "stop"}``."""

    folder.mkdir(parents=True, exist_ok=True)
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])[:MAX_VARIABLES]
        rows = []
        for row in reader:
            if len(rows) >= MAX_ROWS:
                break
            rows.append([_number(cell) for cell in row[: len(header)]])
    width = len(header)
    matrix = np.full((len(rows), width), np.nan)
    for index, row in enumerate(rows):
        matrix[index, : len(row)] = row
    np.save(folder / VALUES, matrix, allow_pickle=False)
    write_json(folder / NAMES, header)
    declared = {item["name"]: item for item in variables_from_init(init_path)}
    variables = []
    for column, name in enumerate(header):
        if name == "time":
            continue
        item = declared.get(name, {"name": name, "description": "", "unit": "", "kind": "variable"})
        values = matrix[:, column] if len(rows) else np.array([])
        finite = values[np.isfinite(values)]
        variables.append(
            {
                **item,
                "column": column,
                "final": float(finite[-1]) if finite.size else None,
                "constant": bool(finite.size and np.all(finite == finite[0])),
            }
        )
    # Parameters are not in the CSV: listed from the model with their start value.
    for name, item in declared.items():
        if item["kind"] == "parameter" and name not in header:
            variables.append({**item, "column": None, "final": None, "constant": True})
    write_json(folder / VARIABLES, variables)
    times = matrix[:, 0] if width and len(rows) else np.array([])
    return {
        "variables": len(variables),
        "rows": len(rows),
        "start": float(times[0]) if times.size else None,
        "stop": float(times[-1]) if times.size else None,
    }


def variables(folder: Path) -> list[dict[str, Any]]:
    try:
        return json.loads((folder / VARIABLES).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _decimate(times: np.ndarray, values: np.ndarray, max_points: int) -> tuple[list, list]:
    count = len(times)
    if count <= max_points:
        index = np.arange(count)
    else:
        buckets = max(1, max_points // 3)
        edges = np.linspace(0, count, buckets + 1, dtype=int)
        picked: list[int] = []
        for start, stop in zip(edges[:-1], edges[1:], strict=True):
            if stop <= start:
                continue
            chunk = values[start:stop]
            picked.append(start)
            if np.isfinite(chunk).any():
                picked.append(start + int(np.nanargmin(chunk)))
                picked.append(start + int(np.nanargmax(chunk)))
        picked.append(count - 1)
        index = np.unique(np.array(picked))
    return (
        [float(value) for value in times[index]],
        [float(value) if math.isfinite(value) else None for value in values[index]],
    )


def series(folder: Path, names: list[str], *, max_points: int = 2000) -> dict[str, Any]:
    """The time axis and the values of ``names`` (unknown names are listed in ``missing``)."""

    try:
        header = json.loads((folder / NAMES).read_text(encoding="utf-8"))
        matrix = np.load(folder / VALUES, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"series": [], "missing": names}
    columns = {name: index for index, name in enumerate(header)}
    times = np.asarray(matrix[:, 0]) if matrix.size else np.array([])
    out, missing = [], []
    for name in names:
        column = columns.get(name)
        if column is None or name == "time":
            missing.append(name)
            continue
        x, y = _decimate(times, np.asarray(matrix[:, column]), max(10, min(max_points, 20_000)))
        out.append({"name": name, "time": x, "values": y})
    return {"series": out, "missing": missing}


def csv_text(folder: Path, names: list[str] | None = None) -> str:
    """The results as CSV (time first), every variable or ``names``, for download."""

    header = json.loads((folder / NAMES).read_text(encoding="utf-8"))
    matrix = np.load(folder / VALUES, mmap_mode="r", allow_pickle=False)
    wanted = [0] + [i for i, name in enumerate(header) if i and (names is None or name in names)]
    lines = [",".join(json.dumps(header[i]) for i in wanted)]
    for row in matrix:
        lines.append(
            ",".join("" if not math.isfinite(row[i]) else repr(float(row[i])) for i in wanted)
        )
    return "\n".join(lines) + "\n"
