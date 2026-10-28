"""The Historian's examples in Notebooks (``Examples/Historian``): reading the archive the way
an engineer studies it, raw samples against means and a long period exported to a file.

They find their own signals, so they run on any installation with signals, the demo included.
Every one is run by the tests against the test plant.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.notebooks import Example, cell

_FIND_A_SIGNAL = """
import pandas as pd

listed = pc.signals()
numeric = listed[listed["kind"].fillna("number").isin(["number", "integer"])] if "kind" in listed else listed
signal = numeric.index[0]
print(signal, "-", numeric.loc[signal].get("name", ""))
"""


def _raw_and_means() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            "Without `step` a read gives the samples **as recorded** (each at its own time); "
            "with `step=60` one mean per minute. Raw samples show what the instrument and the "
            "historian's compression did; means are what a trend draws.",
        ),
        cell("code", _FIND_A_SIGNAL),
        cell(
            "code",
            """
raw = pc.series(signal, "-6h", "now")[signal].dropna()
means = pc.series(signal, "-6h", "now", step=60)[signal].dropna()
print(f"{len(raw)} samples as recorded, {len(means)} one-minute means")
ax = raw.plot(figsize=(10, 3.5), style=".", markersize=3, label="as recorded")
means.plot(ax=ax, label="mean per minute")
ax.legend();
""",
        ),
        cell(
            "markdown",
            "How the samples are spaced: the typical interval, and the gaps much longer than it "
            "(a source that stopped, a compression deadband that is too wide).",
        ),
        cell(
            "code",
            """
spacing = raw.index.to_series().diff().dt.total_seconds().dropna()
typical = float(spacing.median()) if not spacing.empty else 0.0
gaps = spacing[spacing > 5 * typical] if typical else spacing.iloc[0:0]
print(f"typical interval {typical:.1f} s; {len(gaps)} gaps over {5 * typical:.0f} s")
gaps.sort_values(ascending=False).head(10)
""",
        ),
    ]


def _export_a_period() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            "A long period of several signals, read in parts by the library (one request per "
            "day and per 50 signals), as five-minute means, then saved to a file on your "
            "computer: nothing is written to the Historian.",
        ),
        cell("code", _FIND_A_SIGNAL),
        cell(
            "code",
            """
chosen = list(numeric.index[:4])
data = pc.series(chosen, "-7d", "now", step=300)
print(data.shape, "from", data.index.min(), "to", data.index.max())
data.describe().T[["count", "mean", "min", "max"]]
""",
        ),
        cell(
            "code",
            """
from pathlib import Path

path = Path("historian-export.csv")
data.to_csv(path, index_label="time")  # with its offset: the plant's local time
print("saved", path.resolve(), f"({path.stat().st_size} bytes)")
""",
        ),
        cell(
            "code",
            """
(data - data.mean()).div(data.std().replace(0, 1)).plot(
    figsize=(10, 3.5), title="Last week, each signal scaled", legend=False
);
""",
        ),
    ]


EXAMPLES = [
    Example(
        "raw-and-means",
        "Raw samples and means",
        "Read a signal as recorded and as one-minute means, and find the gaps between its samples.",
        _raw_and_means,
    ),
    Example(
        "export-a-period",
        "Export a long period",
        "Read a week of several signals as five-minute means, summarise them and save them to a "
        "CSV file on your computer.",
        _export_a_period,
    ),
]

__all__ = ["EXAMPLES"]
