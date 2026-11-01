"""Studies: what a person wants to learn from a model, and how its simulations compare.

A study runs one model over one time interval. A **sweep** varies parameters: each parameter
takes a range (from, to, a number of values) or a list of values, and the study simulates every
combination, one simulation per combination, all built once by the runner. **Indicators** are
numbers computed from each simulation's results (final, smallest, largest, mean and integral
of a variable, and how it settles: overshoot, settling time and integral of the absolute
deviation from its final value), so the simulations can be ranked, compared and summarised.
"""

from __future__ import annotations

import io
import itertools
import json
import math
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from modelcraft.i18n import t
from modelcraft.omc import results

STATISTICS = ("final", "min", "max", "mean", "integral", "overshoot", "settling", "iae")
# A variable has settled once it stays within this share of its change from its final value.
SETTLED = 0.02
MAX_VALUES_PER_PARAMETER = 1000


class StudyError(ValueError):
    """A study the server refuses, with words a person can act on."""


def parameter_values(item: dict[str, Any]) -> list[float | bool]:
    """The values one swept parameter takes, in order."""

    mode = item.get("mode")
    if mode == "list":
        values = list(item.get("values") or [])
    elif mode == "range":
        start, stop, count = float(item["start"]), float(item["stop"]), int(item["count"])
        if count == 1:
            values = [start]
        else:
            step = (stop - start) / (count - 1)
            values = [round(start + index * step, 12) for index in range(count)]
    else:
        raise StudyError(t("Unknown way to vary {name}: {mode}", name=item.get("name"), mode=mode))
    if not values:
        raise StudyError(t("{name} has no values.", name=item.get("name")))
    if len(values) > MAX_VALUES_PER_PARAMETER:
        raise StudyError(
            t(
                "{name} has more than {n} values.",
                name=item.get("name"),
                n=MAX_VALUES_PER_PARAMETER,
            )
        )
    return values


def combinations(sweep: list[dict[str, Any]]) -> list[dict[str, float | bool]]:
    """Every combination of the swept parameters' values (one simulation each)."""

    if not sweep:
        return [{}]
    names = [item["name"] for item in sweep]
    if len(set(names)) != len(names):
        raise StudyError(t("A parameter is varied twice."))
    lists = [parameter_values(item) for item in sweep]
    count = math.prod(len(values) for values in lists)
    if count > 100_000:
        raise StudyError(t("The sweep would make {n} simulations.", n=f"{count:,}"))
    return [dict(zip(names, values, strict=True)) for values in itertools.product(*lists)]


def count(sweep: list[dict[str, Any]]) -> int:
    return math.prod(len(parameter_values(item)) for item in sweep) if sweep else 1


# How a study drives one of the model's inputs (round 9 M6): a constant, a step at a time
# from the value before to its value, or a ramp from the value before (at ``at``) to its value
# (at ``end``).
SHAPES = ("constant", "step", "ramp")


def input_csv(
    shapes: dict[str, dict[str, Any]], variant: dict[str, Any], options: dict[str, Any]
) -> bytes:
    """omc's ``-csvInput`` file for one simulation: a column per input the study drives, its
    value from the variant when swept, else the study's own; a step's two rows a hair apart."""

    start = float(options.get("start", 0.0))
    stop = float(variant.get("@stop", options.get("stop", 1.0)))
    hair = max(stop - start, 1e-9) * 1e-9
    shaped: dict[str, tuple[list[float], list[float]]] = {}
    times = {start, stop}
    for name, shape in shapes.items():
        value = float(variant.get(name, shape.get("value", 0.0)))
        kind = shape.get("shape", "constant")
        before = value if kind == "constant" else float(shape.get("before", value))
        at = float(shape.get("at", start))
        end = max(float(shape.get("end", stop)), at + hair) if kind == "ramp" else at + hair
        # The whole shape, reaching past the simulation on both sides, then read inside it.
        shaped[name] = (
            [min(start, at) - 1.0, at, end, max(stop, end) + 1.0],
            [before, before, value, value],
        )
        if kind != "constant":
            times.update(time for time in (at, end) if start < time < stop)
    lines = ["time," + ",".join(shaped)]
    for time in sorted(times):
        row = [float(np.interp(time, xs, ys)) for xs, ys in shaped.values()]
        lines.append(",".join(repr(value) for value in [time, *row]))
    return ("\n".join(lines) + "\n").encode("utf-8")


def indicators(folder: Path, variables: list[str]) -> dict[str, dict[str, float | None]]:
    """Final, smallest, largest, time-weighted mean and integral of each variable."""

    try:
        header = json.loads((folder / results.NAMES).read_text(encoding="utf-8"))
        matrix = np.load(folder / results.VALUES, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    columns = {name: index for index, name in enumerate(header)}
    times = np.asarray(matrix[:, 0], dtype=float) if matrix.size else np.array([])
    found: dict[str, dict[str, float | None]] = {}
    for name in variables:
        column = columns.get(name)
        if column is None or name == "time" or not times.size:
            continue
        values = np.asarray(matrix[:, column], dtype=float)
        keep = np.isfinite(values) & np.isfinite(times)
        t, v = times[keep], values[keep]
        if not v.size:
            found[name] = dict.fromkeys(STATISTICS)
            continue
        span = float(t[-1] - t[0]) if t.size > 1 else 0.0
        integral = float(np.trapezoid(v, t)) if t.size > 1 else 0.0
        found[name] = {
            "final": float(v[-1]),
            "min": float(v.min()),
            "max": float(v.max()),
            "mean": integral / span if span > 0 else float(v.mean()),
            "integral": integral,
            **settling(t, v),
        }
    return found


def settling(t: np.ndarray, v: np.ndarray) -> dict[str, float | None]:
    """How a variable reaches its final value: the overshoot past it (in % of its change from
    the first value), the time from the start until it stays within 2 % of that change, and
    the integral of its absolute deviation from the final value."""

    if t.size < 2:
        return {"overshoot": None, "settling": None, "iae": None}
    final = float(v[-1])
    deviation = np.abs(v - final)
    iae = float(np.trapezoid(deviation, t))
    change = final - float(v[0])
    scale = max(abs(change), float(np.ptp(v)))
    if scale <= 1e-12 * max(1.0, abs(final)):
        return {"overshoot": 0.0, "settling": 0.0, "iae": iae}
    past = (v - final) * (1 if change >= 0 else -1)
    overshoot = float(max(0.0, past.max()) / abs(change) * 100) if abs(change) > 1e-12 else None
    outside = np.nonzero(deviation > SETTLED * scale)[0]
    settled = float(t[min(outside[-1] + 1, t.size - 1)] - t[0]) if outside.size else 0.0
    return {"overshoot": overshoot, "settling": settled, "iae": iae}


def summary(values: list[float]) -> dict[str, float | int | None]:
    """Mean, standard deviation and percentiles of one indicator over the simulations."""

    clean = np.array([value for value in values if value is not None and math.isfinite(value)])
    if not clean.size:
        return {
            "n": 0,
            "mean": None,
            "std": None,
            "min": None,
            "p5": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    return {
        "n": int(clean.size),
        "mean": float(clean.mean()),
        "std": float(clean.std(ddof=1)) if clean.size > 1 else 0.0,
        "min": float(clean.min()),
        "p5": float(np.percentile(clean, 5)),
        "p50": float(np.percentile(clean, 50)),
        "p95": float(np.percentile(clean, 95)),
        "max": float(clean.max()),
    }


def statistics(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For every indicator of the finished simulations: its summary over them."""

    rows: dict[tuple[str, str], list[float]] = {}
    for run in runs:
        if run["status"] != "done":
            continue
        for variable, stats in ((run.get("result") or {}).get("indicators") or {}).items():
            for statistic in STATISTICS:
                rows.setdefault((variable, statistic), []).append(stats.get(statistic))
    return [
        {"variable": variable, "statistic": statistic, **summary(values)}
        for (variable, statistic), values in rows.items()
    ]


def envelope(
    folder_of, runs: list[dict[str, Any]], name: str, points: int = 1000
) -> dict[str, Any] | None:
    """Smallest, 5th, 50th, 95th percentile and largest value of ``name`` over the runs, on
    one time axis (each run's values interpolated onto it)."""

    curves, start, stop = [], None, None
    for run in runs:
        answer = results.series(folder_of(run["id"]), [name], max_points=20_000)
        if not answer["series"]:
            continue
        item = answer["series"][0]
        t = np.array(item["time"], dtype=float)
        v = np.array([np.nan if value is None else value for value in item["values"]], dtype=float)
        if t.size < 2:
            continue
        curves.append((t, v))
        start = t[0] if start is None else min(start, t[0])
        stop = t[-1] if stop is None else max(stop, t[-1])
    if not curves or start is None or stop is None or stop <= start:
        return None
    grid = np.linspace(start, stop, max(10, min(points, 5000)))
    stack = np.vstack([np.interp(grid, t, v, left=np.nan, right=np.nan) for t, v in curves])
    with np.errstate(all="ignore"):
        bands = {
            "min": np.nanmin(stack, axis=0),
            "p5": np.nanpercentile(stack, 5, axis=0),
            "p50": np.nanpercentile(stack, 50, axis=0),
            "p95": np.nanpercentile(stack, 95, axis=0),
            "max": np.nanmax(stack, axis=0),
        }

    def clean(values: np.ndarray) -> list[float | None]:
        return [float(value) if math.isfinite(value) else None for value in values]

    return {
        "name": name,
        "runs": len(curves),
        "time": [float(value) for value in grid],
        **{key: clean(values) for key, values in bands.items()},
    }


# Export -------------------------------------------------------------------------------------


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else ""
    text = str(value)
    return json.dumps(text) if any(c in text for c in ',"\n') else text


def parameters_csv(study: dict[str, Any], runs: list[dict[str, Any]]) -> str:
    """One row per simulation: its id, status, the swept values and every indicator."""

    swept = [item["name"] for item in (study.get("spec") or {}).get("sweep") or []]
    swept += sorted({name for run in runs for name in (run.get("variant") or {})} - set(swept))
    measured = sorted(
        {
            (variable, statistic)
            for run in runs
            for variable, stats in ((run.get("result") or {}).get("indicators") or {}).items()
            for statistic in stats
        }
    )
    header = ["run_id", "status", "label", *swept, *(f"{v}:{s}" for v, s in measured)]
    lines = [",".join(_csv_value(name) for name in header)]
    for run in runs:
        found = (run.get("result") or {}).get("indicators") or {}
        row = [run["id"], run["status"], run.get("label") or ""]
        row += [(run.get("variant") or {}).get(name) for name in swept]
        row += [(found.get(v) or {}).get(s) for v, s in measured]
        lines.append(",".join(_csv_value(value) for value in row))
    return "\n".join(lines) + "\n"


def results_csv(folder_of, runs: list[dict[str, Any]]) -> str:
    """Every finished simulation's results in one table: ``run_id``, ``time``, the variables
    (the same model, so the same columns; a column a run lacks is empty)."""

    columns: list[str] = []
    tables = []
    for run in runs:
        if run["status"] != "done":
            continue
        folder = folder_of(run["id"])
        try:
            header = json.loads((folder / results.NAMES).read_text(encoding="utf-8"))
            matrix = np.load(folder / results.VALUES, mmap_mode="r", allow_pickle=False)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for name in header:
            if name not in columns:
                columns.append(name)
        tables.append((run["id"], header, matrix))
    out = io.StringIO()
    out.write(",".join(_csv_value(name) for name in ["run_id", *columns]) + "\n")
    for run_id, header, matrix in tables:
        place = [header.index(name) if name in header else None for name in columns]
        for row in matrix:
            cells = [run_id] + [
                "" if index is None or not math.isfinite(row[index]) else repr(float(row[index]))
                for index in place
            ]
            out.write(",".join(cells) + "\n")
    return out.getvalue()


def notebook(study: dict[str, Any], variables: list[str]) -> str:
    """A Jupyter notebook that loads the exported study and redraws its main charts."""

    first = variables[0] if variables else "time"
    swept = [item["name"] for item in (study.get("spec") or {}).get("sweep") or []]

    def cell(kind: str, source: str) -> dict[str, Any]:
        base = {"cell_type": kind, "metadata": {}, "source": source.strip("\n").splitlines(True)}
        if kind == "code":
            base.update(execution_count=None, outputs=[])
        return base

    cells = [
        cell(
            "markdown",
            f"""
# {study["name"]}

Model `{study["model"]}` of project **{study["project_name"]}**, exported from PlantCraft Models.

- `parameters.csv`: one row per simulation, with the values it used and its indicators.
- `results.csv`: every finished simulation's results (`run_id`, `time`, the variables).
- `model/`: the Modelica files as they were when the study ran.
""",
        ),
        cell(
            "code",
            """
import pandas as pd
import matplotlib.pyplot as plt

parameters = pd.read_csv("parameters.csv")
results = pd.read_csv("results.csv")
parameters.head()
""",
        ),
        cell(
            "code",
            f"""
# One variable of every simulation, over time.
variable = {json.dumps(first)}
fig, ax = plt.subplots(figsize=(9, 4))
for run_id, run in results.groupby("run_id"):
    ax.plot(run["time"], run[variable], linewidth=1, alpha=0.6)
ax.set_xlabel("time (s)")
ax.set_ylabel(variable)
ax.set_title(variable + " in every simulation")
plt.show()
""",
        ),
        cell(
            "code",
            """
# The spread over the simulations: median and the band between the 5th and 95th percentiles.
grid = results.pivot_table(index="time", columns="run_id", values=variable)
fig, ax = plt.subplots(figsize=(9, 4))
ax.fill_between(grid.index, grid.quantile(0.05, axis=1), grid.quantile(0.95, axis=1), alpha=0.3)
ax.plot(grid.index, grid.median(axis=1), linewidth=2)
ax.set_xlabel("time (s)")
ax.set_ylabel(variable)
plt.show()
""",
        ),
    ]
    if swept:
        cells.append(
            cell(
                "code",
                f"""
# A swept parameter against an indicator.
parameter = {json.dumps(swept[0])}
indicator = {json.dumps(f"{first}:final")}
if indicator in parameters:
    parameters.plot.scatter(x=parameter, y=indicator, figsize=(6, 4))
    plt.show()
parameters.describe()
""",
            )
        )
    return json.dumps(
        {
            "cells": cells,
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python"},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        },
        indent=1,
    )


def export_zip(
    study: dict[str, Any], runs: list[dict[str, Any]], files: dict[str, str], folder_of
) -> bytes:
    variables = list((study.get("spec") or {}).get("indicators") or [])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("parameters.csv", parameters_csv(study, runs))
        archive.writestr("results.csv", results_csv(folder_of, runs))
        archive.writestr("study.ipynb", notebook(study, variables))
        archive.writestr(
            "study.json",
            json.dumps(
                {
                    key: study.get(key)
                    for key in (
                        "id",
                        "name",
                        "description",
                        "project_name",
                        "model",
                        "kind",
                        "spec",
                        "created_by",
                        "created_at",
                    )
                },
                indent=2,
            ),
        )
        for path, text in files.items():
            archive.writestr(f"model/{path}", text)
        archive.writestr(
            "README.md",
            f"# {study['name']}\n\nOpen `study.ipynb` in Jupyter (pandas and matplotlib) to start "
            "the analysis. `parameters.csv` has one row per simulation; `results.csv` has every "
            "finished simulation's results; `model/` holds the Modelica files as they were.\n",
        )
    return buffer.getvalue()
