"""Models' examples in Notebooks (``Examples/Models``): its models and their runs read with
``pc.app("models")``, and a simulation queued from a notebook when an administrator allows it.

They find their own model and run, so they run on any installation with Models, the demo
included. Every one is run by the tests against the test plant.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.notebooks import Example, cell

_RESULTS = """
def results_table(run):
    \"\"\"A finished simulation's results: one column per variable, by simulation time.\"\"\"
    columns = {
        name: pd.Series(serie["values"], index=serie["time"], name=name)
        for name, serie in (run.get("results") or {}).items()
    }
    return pd.DataFrame(columns).sort_index()
"""


def _models_and_runs() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            '`pc.app("models")` reads Models with your access: its models (the examples first) '
            "and every simulation that ran, with its results.",
        ),
        cell(
            "code",
            """
import pandas as pd

models = pc.app("models")
listed = models.models()
listed[["name", "project", "example"]].head(15)
""",
        ),
        cell(
            "markdown",
            "One model, whole: its settings (start, stop, solver), its inputs, outputs and "
            "parameters as Link's blocks show them.",
        ),
        cell(
            "code",
            """
model = models.get("model", listed.index[0])
print(model["name"], "-", model["description"])
model["settings"]
""",
        ),
        cell(
            "code",
            """
runs = models.runs()
runs[["name", "model", "status", "created_at"]].head(10) if not runs.empty else runs
""",
        ),
        cell(
            "markdown",
            "A finished simulation carries its results (each variable thinned to 2000 points): "
            "here as a table, and plotted.",
        ),
        cell("code", _RESULTS),
        cell(
            "code",
            """
done = runs[(runs["status"] == "done") & (runs["kind_of_run"] == "simulate")] if not runs.empty else runs
if done.empty:
    print("No finished simulation yet: simulate a model in Models once.")
else:
    run = models.get("run", done.index[0])
    table = results_table(run)
    print(run["name"], "-", len(table.columns), "variables")
    table.iloc[:, :6].plot(figsize=(10, 3.5), title=run["name"]);
""",
        ),
    ]


def _simulate_a_model() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            "`model.run(...)` queues a simulation in Models' own queue, as the page's Simulate "
            "does: it runs in Models (OpenModelica), not here. An administrator allows it in "
            "PlantCraft › Setup › Apps › Models (**Simulations from notebooks**, off by default), "
            "and you need to be an editor of Models.",
        ),
        cell(
            "code",
            """
import pandas as pd

models = pc.app("models")
listed = models.models()
chosen = listed[listed["example"]].index[0] if listed["example"].any() else listed.index[0]
model = models.get("model", chosen)
print(model["name"], model["settings"])
""",
        ),
        cell("code", _RESULTS),
        cell(
            "markdown",
            "Twice as long as the model's own stop time, with a label to find it in Models' "
            "Runs. `.wait()` reads the run again until it ends.",
        ),
        cell(
            "code",
            """
stop = float(model["settings"].get("stop") or 1) * 2
try:
    run = model.run(stop=stop, label="From a notebook").wait(timeout=600)
except pc.PlantCraftError as refused:
    run = None
    print(refused)
if run is not None:
    print(run["status"], run.get("error") or "")
    if run["status"] == "done":
        results_table(run).iloc[:, :6].plot(figsize=(10, 3.5), title=f"{model['name']} to {stop:g} s");
""",
        ),
    ]


EXAMPLES = [
    Example(
        "models-and-runs",
        "Models and their runs",
        "List Models' models, read one with its settings and ports, and plot a finished "
        "simulation's results.",
        _models_and_runs,
    ),
    Example(
        "simulate-a-model",
        "Simulate a model",
        "Queue a simulation in Models from a notebook (when an administrator allows it), wait "
        "for it and plot its results.",
        _simulate_a_model,
    ),
]

__all__ = ["EXAMPLES"]
