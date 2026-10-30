"""The notebooks PlantCraft writes: the first cells already load what the person was looking at.

Every notebook starts the same way: install the ``plantcraft-notebook`` package (served by
PlantCraft itself, offline) and import it as ``pc``. The cells after that depend on where the
person came from: signals over a period (Historian, View, a signal), one asset, or nothing.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.notebooks import MODULE, PACKAGE, Example
from plantcraft_sdk.notebooks import cell as _cell
from plantcraft_sdk.notebooks import literal as _literal
from plantcraft_sdk.notebooks import notebook as _notebook
from plantcraft_sdk.notebooks import setup as _setup

__all__ = ["MODULE", "PACKAGE"]


def series_notebook(
    signals: list[str], start: str, end: str, *, step: int | None = None, origin: str = ""
) -> tuple[str, dict[str, Any]]:
    """Signals over a period: one table indexed by the plant's local time, a chart and a summary."""

    names = ", ".join(signals[:3]) + (f" and {len(signals) - 3} more" if len(signals) > 3 else "")
    title = f"{names} {start[:10]}"
    where = f" from {origin}" if origin else ""
    intro = f"""
# {names}

Opened{where} in PlantCraft. Times are the plant's local time. Run each cell with **Shift + Enter**.

This notebook runs in your browser and reads the plant with your own access. Your changes stay
in this browser: **File › Download** keeps a copy (`.ipynb`) that also runs in Jupyter on your
computer (Help › Notebooks).
"""
    step_line = (
        f"step = {step}  # seconds between values" if step else "step = None  # recorded values"
    )
    cells = _setup(intro) + [
        _cell(
            "code",
            f"""
signals = {_literal(signals)}
start, end = {_literal(start)}, {_literal(end)}
{step_line}
data = pc.series(signals, start, end, step=step)
data
""",
        ),
        _cell("code", "data.plot(subplots=True, figsize=(10, 2 + 2 * len(data.columns)));"),
        _cell("code", "data.describe()"),
    ]
    return title, _notebook(cells)


def asset_notebook(asset_id: str, name: str = "") -> tuple[str, dict[str, Any]]:
    """One asset: its record, its signals by role and the last day of them."""

    label = name or asset_id
    intro = f"""
# {label}

Opened from the asset page in PlantCraft. Times are the plant's local time. Run each cell with **Shift + Enter**.

This notebook runs in your browser and reads the plant with your own access. **File › Download**
keeps a copy (`.ipynb`).
"""
    cells = _setup(intro) + [
        _cell("code", f"asset = pc.asset({_literal(asset_id)})\nasset"),
        _cell(
            "code",
            """
roles = asset["signals"]  # role -> signal id
data = pc.series(list(roles.values()), "-24h", "now", step=60)
data.columns = [role for role in roles]
data.plot(subplots=True, figsize=(10, 2 + 2 * len(data.columns)));
""",
        ),
    ]
    return label, _notebook(cells)


def blank_notebook() -> tuple[str, dict[str, Any]]:
    intro = """
# New notebook

Run each cell with **Shift + Enter**. `pc` reads the plant with your own access:
`pc.signals("FIC")`, `pc.series([...], "-7d", "now", step=60)`, `pc.assets(type="loop")`,
`pc.results(subject="asset:...")`. `help(pc)` lists everything.
"""
    cells = _setup(intro) + [_cell("code", "pc.signals().head(20)")]
    return "Untitled", _notebook(cells)


# Examples ------------------------------------------------------------------------------
# Ready notebooks that show how to use the plant's data ("colocar exemplos";
# 2026-10-26: four, none repeated, in Examples/PlantCraft beside each app's folder). They find
# their own signals and assets, so they run on any installation, the demo included.

_FIRST_NUMBER = """
found = pc.signals()
numbers = found[found["kind"] != "text"] if "kind" in found.columns else found
numbers.head(10)
"""


def _first_steps() -> list[dict[str, Any]]:
    return [
        _cell(
            "markdown",
            "`pc.me()` above says who the notebook reads as: it never sees more than you may. "
            'First, the signals with a number (`pc.signals("FIC")` finds by id, name or '
            "description).",
        ),
        _cell("code", _FIRST_NUMBER),
        _cell(
            "markdown",
            "Pick one signal by its id (the table's index). The first one is used here; write any "
            "other id between the quotes. `step=60` gives one mean per minute.",
        ),
        _cell(
            "code",
            """
signal = numbers.index[0]
data = pc.series(signal, "-7d", "now", step=60)[signal].dropna()
data.plot(figsize=(10, 3), title=signal);
""",
        ),
        _cell("code", f"pc.value(signal, agg={_literal('mean')}, window={_literal('24h')})"),
        _cell("markdown", "Summary numbers, a rolling mean and how often each value happens."),
        _cell(
            "code",
            """
print(data.describe())
fig, (left, right) = plt.subplots(1, 2, figsize=(11, 3.5))
data.plot(ax=left, alpha=0.5, label="value")
data.rolling(60).mean().plot(ax=left, label="mean of the last hour")
left.legend()
data.plot.hist(ax=right, bins=40, title="How often each value happens");
""",
        ),
        _cell(
            "markdown",
            "Values more than 3 standard deviations away from the mean: candidates to look at.",
        ),
        _cell("code", "z = (data - data.mean()) / data.std()\ndata[z.abs() > 3]"),
    ]


def _compare_example() -> list[dict[str, Any]]:
    return [
        _cell("code", _FIRST_NUMBER),
        _cell(
            "code",
            """
chosen = list(numbers.index[:3])  # or a list of your own ids
data = pc.series(chosen, "-7d", "now", step=600)  # one mean every 10 minutes
data.plot(subplots=True, sharex=True, figsize=(10, 2 + 2 * len(chosen)));
""",
        ),
        _cell(
            "markdown",
            "Each signal on its own scale: subtract the mean and divide by the standard "
            "deviation, so they can be drawn together.",
        ),
        _cell(
            "code",
            """
scaled = (data - data.mean()) / data.std()
scaled.plot(figsize=(10, 3.5));
scaled.corr().round(2)  # how the signals move together
""",
        ),
    ]


def _asset_example() -> list[dict[str, Any]]:
    return [
        _cell("code", "tree = pc.assets()\ntree.head(15)"),
        _cell(
            "markdown",
            "Find an asset that has signals bound by role (a pump's flow, a loop's PV, SP and OP).",
        ),
        _cell(
            "code",
            """
asset = None
for asset_id in tree.index:
    record = pc.asset(asset_id)
    if record.get("signals"):
        asset = record
        break
asset
""",
        ),
        _cell(
            "code",
            """
roles = asset["signals"]  # role -> signal id
data = pc.series(list(roles.values()), "-24h", "now", step=60)
data.columns = list(roles)
data.plot(subplots=True, sharex=True, figsize=(10, 2 + 2 * len(roles)), title=asset["name"]);
""",
        ),
    ]


def _events_example() -> list[dict[str, Any]]:
    return [
        _cell(
            "markdown",
            "The last result each app published about each subject: loop health, signal "
            "quality, alarms. Empty while no app has run yet.",
        ),
        _cell("code", "found = pc.results()\nfound.head(20)"),
        _cell(
            "code",
            """
if found.empty:
    print("No results yet: open an app and let it run once.")
else:
    print(found.groupby(["app", "kind"]).size().rename("results"))
""",
        ),
        _cell(
            "markdown",
            "Events are what happened: a finding, an alarm raised or cleared, an action. "
            "Here the last 200, counted per day.",
        ),
        _cell("code", "events = pc.events(limit=200)\nevents.head(20)"),
        _cell(
            "code",
            """
if events.empty:
    print("No events yet.")
else:
    events["at"] = pd.to_datetime(events["at"], utc=True)
    per_day = events.set_index("at").groupby("kind").resample("1D").size().unstack(0).fillna(0)
    per_day.plot.bar(stacked=True, figsize=(10, 3.5), title="Events per day");
""",
        ),
    ]


EXAMPLES: dict[str, Example] = {
    item.id: item
    for item in (
        Example(
            "first-steps",
            "First steps",
            "Who the notebook reads as, find signals, read one and plot it, summary numbers and "
            "the values that stand out.",
            _first_steps,
        ),
        Example(
            "compare-signals",
            "Compare signals over a period",
            "Several signals over a week, on one scale, and how they move together.",
            _compare_example,
        ),
        Example(
            "asset-signals",
            "An asset and its signals",
            "Walk the plant tree, open an asset and load its signals by role.",
            _asset_example,
        ),
        Example(
            "events-and-results",
            "Events and results",
            "What the apps published (loop health, signal quality, alarms) and what happened, "
            "per app and per day.",
            _events_example,
        ),
    )
}
# The titles of the examples before 2026-10-26: their old copies in My notebooks are removed
# once (``plantcraft.notebooks``, migration "example-copies-2026-10-26").
OLD_EXAMPLE_TITLES = (
    "Read a signal and plot it",
    "Compare signals over a period",
    "An asset and its signals",
    "Statistics and a histogram",
    "What the apps found",
    "Events over time",
)


def examples() -> list[dict[str, str]]:
    return [item.item() for item in EXAMPLES.values()]


def example_notebook(example_id: str) -> tuple[str, dict[str, Any]]:
    """One example as the Examples folder shows it, the setup cells first like every notebook."""

    found = EXAMPLES[example_id]
    return found.title, found.notebook()
