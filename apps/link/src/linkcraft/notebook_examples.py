"""Link's examples in Notebooks (``Examples/Analytics``): blocks and algorithms run on the person's
computer or in their browser (``linkcraft.notebook``), and Link's results.

They find their own loop, so they run on any installation with a loop whose PV and SP are bound,
the demo included. Every one is run by the tests against the test plant.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.notebooks import Example, cell

_FIND_A_LOOP = """
link = pc.app("link")
loop = None
for loop_id in pc.assets(type="loop").index:
    record = pc.asset(loop_id)
    if {"pv", "sp"} <= set(record.get("signals") or {}):
        loop = record
        break
print(link)
loop["name"], loop["signals"]
"""


def _run_a_block() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            '`pc.app("link")` reads Link with your access; `link.blocks()` lists every block '
            "of its catalog, Link's own and the ones written on this site.",
        ),
        cell("code", _FIND_A_LOOP),
        cell("code", 'link.blocks()[["name", "library", "inputs", "outputs"]].head(20)'),
        cell(
            "markdown",
            "A block runs **here**, with the code Link runs, on data read over the window. "
            "`asset=` reads each input from the loop's signals by role (`pv` unless "
            "`roles={...}` says otherwise).",
        ),
        cell(
            "code",
            """
spikes = link.get("block", "dq.spikes")
print(spikes["summary"])
run = spikes.run(asset=loop["id"], start="-24h")
run.values()
""",
        ),
        cell(
            "markdown",
            "Or give it a series of your own: here the PV's mean per minute, smoothed by "
            "`transform.moving_average` (parameters by name).",
        ),
        cell(
            "code",
            """
pv = loop["signals"]["pv"]
data = pc.series(pv, "-24h", "now", step=60)[pv].dropna()
smooth = link.get("block", "transform.moving_average").run(x=data, window_samples=30)
ax = data.plot(figsize=(10, 3), alpha=0.5, label="PV")
smooth.table()["value"].plot(ax=ax, label="moving average")
ax.legend();
""",
        ),
        cell(
            "markdown",
            "Two inputs: how far the PV stays from its set point (`cpm.error_metrics_basic`).",
        ),
        cell(
            "code",
            """
errors = link.get("block", "cpm.error_metrics_basic")
errors.run(asset=loop["id"], roles={"pv": "pv", "sp": "sp"}, start="-24h").values()
""",
        ),
    ]


def _write_a_block() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            "A block is one JSON document: its contract (inputs, outputs, parameters) and its "
            "Python code, `run(inputs, params, ctx)`. Write one here, test it on real data, then "
            "import the file in Link (Blocks › Import): Link checks it again and keeps its "
            "versions.",
        ),
        cell("code", _FIND_A_LOOP),
        cell(
            "code",
            '''
block = {
    "format": "plantcraft-block/1",
    "name": "Time above a limit",
    "library": "custom",
    "docs": {"summary": "Share of the window a series spends above a limit."},
    "inputs": [{"port": "x", "type": "series", "label": "Signal"}],
    "outputs": [{"port": "share", "type": "number", "label": "Share above", "unit": "%"}],
    "parameters": [{"name": "limit", "type": "number", "title": "Limit", "default": 0}],
    "code": """
def run(inputs, params, ctx):
    x = inputs["x"].dropna()
    if x.empty:
        return {"share": None}
    return {"share": float((x > params.limit).mean() * 100)}
""",
}
''',
        ),
        cell(
            "markdown",
            "Test it: `link.test_block` runs the file the way Link's own test does (its code "
            "checked first, the same allowed modules), here on your computer.",
        ),
        cell(
            "code",
            """
pv = loop["signals"]["pv"]
data = pc.series(pv, "-24h", "now", step=60)[pv].dropna()
limit = float(data.median())
runtime = link.runtime()
run = runtime.test_block(block, x=data, limit=limit)
run.values()
""",
        ),
        cell(
            "markdown",
            "Happy with it? Save the file and import it in Link (Blocks › Import). It is a "
            "file on your computer until then: nothing was sent to Link.",
        ),
        cell(
            "code",
            """
import json
from pathlib import Path

Path("time_above_a_limit.block.json").write_text(json.dumps(block, indent=2))
""",
        ),
    ]


def _run_an_algorithm() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            "An algorithm is a diagram of blocks. `run` runs all of it on one loop over its own "
            "window (or the one you give), here, and compares with what Link published.",
        ),
        cell("code", _FIND_A_LOOP),
        cell("code", 'link.algorithms()[["name", "description", "version"]]'),
        cell(
            "code",
            """
algorithms = link.algorithms()
chosen = next(
    (key for key, name in algorithms["name"].items() if "flow" in str(name).lower()),
    algorithms.index[0],
)
algorithm = link.get("algorithm", chosen)
print(algorithm["name"], "-", algorithm["description"])
run = algorithm.run(asset=loop["id"], start="-6h")
run.verdict
""",
        ),
        cell("code", "run.values()"),
        cell(
            "markdown",
            "What Link published for this loop (its last results), beside the run above.",
        ),
        cell("code", 'pc.results(subject=f"asset:{loop[\'id\']}", app="linkcraft")'),
    ]


def _loop_health() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            "Link scores every loop's health (0 to 100) and names what limits it. Here the "
            "portfolio, worst first, and the score of the worst loops over the last week.",
        ),
        cell(
            "code",
            """
health = pc.results(app="linkcraft", kind="loop_health")
if health.empty:
    print("No loop health yet: let Link's loop round run once.")
else:
    table = health.sort_values("value")[["subject", "status", "value", "summary"]]
    table.head(15)
""",
        ),
        cell(
            "code",
            """
if not health.empty:
    worst = [subject.split(":", 1)[1] for subject in table["subject"].head(5)]
    # Each loop's score is app-linkcraft:<loop>.<algorithm>.health.
    names = {}
    for loop in worst:
        found = [i for i in pc.signals(loop).index if i.startswith(f"app-linkcraft:{loop}.") and i.endswith(".health")]
        if found:
            names[found[0]] = loop
    scores = pc.series(list(names), "-7d", "now", step=3600).rename(columns=names)
    scores.plot(figsize=(10, 3.5), title="Loop health, last week (100 is best)");
""",
        ),
    ]


EXAMPLES = [
    Example(
        "run-a-block",
        "Run a block",
        "List Link's blocks and run some on your computer: on a loop's signals, on a series of "
        "your own, and with two inputs.",
        _run_a_block,
    ),
    Example(
        "write-a-block",
        "Write and test a block",
        "Write a block in Link's format, test it on real data on your computer and save the "
        "file to import in Link.",
        _write_a_block,
    ),
    Example(
        "run-an-algorithm",
        "Run an algorithm",
        "Run one of Link's algorithms on a loop, here, and compare with what Link published.",
        _run_an_algorithm,
    ),
    Example(
        "loop-health",
        "Loop health",
        "Link's loop health scores: the portfolio worst first and the worst loops over a week.",
        _loop_health,
    ),
]

__all__ = ["EXAMPLES"]
