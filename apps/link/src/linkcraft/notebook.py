"""Link's blocks and algorithms in a notebook, on the person's computer or in their browser.

PlantCraft's notebook library copies Link's packages there (``[contributes.notebooks]`` in
``app.toml``) and calls ``run`` when a notebook runs a block or an algorithm::

    link = pc.app("link")
    link.get("block", "stats.mean").run(asset="FIC-101", start="-24h")
    link.get("block", "stats.mean").run(x=data["plant:FIC-101.PV"])     # a series of your own
    link.get("algorithm", "loop-health").run(asset="FIC-101")

It is the code Link runs (``assets.run``), on data read through PlantCraft with the person's
access. Nothing runs on Link's server and nothing is written anywhere: not Link's results, not
the Historian. A block written on the site runs its code here the way Link's own test does
(``blocks.sandbox``, its checks and allowed modules), and a block of a model (an FMU) gives no
value outside Link.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import NoData, Result
from plantcraft_sdk.client import NotFound, PlantCraftError

from linkcraft.assets.run import (
    MAX_POINTS,
    AssetTiming,
    _plan,
    _run_plan,
    block_diagram,
    run_on_asset,
    timing_of,
    window_end,
)
from linkcraft.blocks import CATALOG, sandbox, site
from linkcraft.blocks.files import read_file

# Block code runs in the notebook's own process: it is the person's computer.
sandbox.use_pool(sandbox.InlinePool())


class PlantReader:
    """What ``assets.run`` reads (an asset, series), through the notebook library."""

    def __init__(self, plant: Any, raw: bool = False):
        self.plant = plant
        # Read as recorded (no step): what the quality checks need to judge.
        self.raw = raw

    def asset(self, asset_id: str) -> dict[str, Any]:
        try:
            return dict(self.plant.asset(asset_id))
        except self.plant.PlantCraftError as exc:
            kind = NotFound if exc.status == 404 else PlantCraftError
            raise kind(str(exc), status_code=exc.status) from exc

    def series_many_pandas(
        self, signal_ids: list[str], start: Any, end: Any, step: float | None
    ) -> tuple[dict[str, pd.Series], list[dict[str, Any]]]:
        try:
            frame = self.plant.series(list(signal_ids), start, end, step=None if self.raw else step)
        except self.plant.PlantCraftError as exc:
            raise PlantCraftError(str(exc), status_code=exc.status) from exc
        columns = {name: frame[name] for name in frame.columns}
        for series in columns.values():
            series.attrs["recorded"] = self.raw
        return columns, []


@dataclass
class Run:
    """One run in a notebook: what each output gave (pandas Series, numbers, verdicts), the
    run's verdict and Link's summary of it."""

    outputs: dict[str, Any]
    verdict: dict[str, Any]
    window: dict[str, Any]
    summary: dict[str, Any] = field(repr=False, default_factory=dict)

    def results(self) -> pd.DataFrame:
        """What the run would publish (its output blocks: results, values, messages), one row
        each, as Link publishes them after a scheduled run."""

        rows = [
            {key: item.get(key) for key in ("name", "kind", "status", "value", "message")}
            for item in self.summary.get("outputs") or []
        ]
        return pd.DataFrame(rows, columns=["name", "kind", "status", "value", "message"])

    def table(self) -> pd.DataFrame:
        """The outputs that are series, one column each (time in UTC)."""

        series = {key: value for key, value in self.outputs.items() if isinstance(value, pd.Series)}
        return pd.DataFrame(series)

    def values(self) -> dict[str, Any]:
        """Each output as plain values: a number, a verdict as a dict, a series' last value."""

        found: dict[str, Any] = {}
        for key, value in self.outputs.items():
            if isinstance(value, Result):
                found[key] = value.as_dict()
            elif isinstance(value, NoData):
                found[key] = f"no value: {value.reason}"
            elif isinstance(value, pd.Series):
                found[key] = value.dropna().iloc[-1] if not value.dropna().empty else None
            else:
                found[key] = value
        return found

    def plot(self, **options: Any) -> Any:
        table = self.table()
        if table.empty:
            raise ValueError("No output of this run is a series.")
        options.setdefault("subplots", True)
        options.setdefault("figsize", (10, 2 + 2 * len(table.columns)))
        return table.plot(**options)


def _window(
    timing: AssetTiming, start: Any, end: Any, step: float | None, plant: Any
) -> tuple[pd.Timestamp, pd.Timestamp, float]:
    """The run's window: ``start`` and ``end`` as the notebook library reads times (``"-24h"``,
    ``"now"``, an ISO text), else the algorithm's own; without ``step``, the algorithm's, widened
    so a long window keeps at most ``MAX_POINTS`` steps."""

    finish = pd.Timestamp(plant.moment(end if end is not None else "now"))
    begin = (
        pd.Timestamp(plant.moment(start))
        if start is not None
        else finish - pd.Timedelta(seconds=timing.window_seconds)
    )
    if begin >= finish:
        raise ValueError("start must come before end")
    if not step:
        span = (finish - begin).total_seconds()
        step = max(timing.step_seconds, math.ceil(span / MAX_POINTS))
    finish = window_end(finish, float(step))
    return begin, finish, float(step)


def _site_block(block_id: str, app: Any, item: dict[str, Any] | None = None) -> None:
    """A block written on the site (Link's catalog here has only the blocks Link ships): its
    file, from ``item`` or from Link, into this catalog, its code checked as Link checks it."""

    if block_id in CATALOG:
        return
    if item is None:
        try:
            item = app.get("block", block_id)
        except Exception as exc:  # noqa: BLE001 - said in one line
            raise LookupError(f"Block {block_id} is not in Link: {exc}") from exc
    file = item.get("file")
    if not isinstance(file, dict) or not file.get("code"):
        raise LookupError(f"Block {block_id} does not run outside Link.")
    found = read_file(file)
    problems = sandbox.check_code(found.code)
    if problems:
        raise ValueError(f"Block {block_id} cannot run: {' '.join(problems)}")
    CATALOG[block_id] = site.code_block(found, block_id)


def _summary_run(ran: dict[str, Any], keep: list[tuple[str, str]]) -> Run:
    summary = ran.get("summary") or {}
    kept = ran.get("kept") or {}
    outputs = {
        (port if node == "block" else f"{node}.{port}"): kept.get((node, port))
        for node, port in keep
    }
    return Run(
        outputs=outputs,
        verdict=summary.get("verdict") or {},
        window=summary.get("window") or {},
        summary=summary,
    )


# Blocks that judge samples as recorded (gaps, frozen values, spikes).
RAW_FIRST = ("dq.",)


def run_block(
    item: dict[str, Any],
    plant: Any,
    app: Any,
    *,
    asset: str | None = None,
    start: Any = None,
    end: Any = None,
    step: float | None = None,
    roles: dict[str, str] | None = None,
    **given: Any,
) -> Run:
    """Run one block. Each input comes from ``asset``'s signals by role (``roles={"x": "pv"}``;
    without roles every required input reads ``pv``), or is given by its name: a signal id
    (``x="plant:FIC-101.PV"``, read over the window) or a pandas Series of your own
    (``x=data["plant:FIC-101.PV"]``: the window is then what the series cover). Every other name
    is one of the block's parameters (``window_hours=2``)."""

    block_id = str(item.get("block_id") or item.get("id"))
    _site_block(block_id, app, item)
    spec = CATALOG[block_id].spec
    ports = {port.port_id for port in spec.inputs}
    inputs = {key: value for key, value in given.items() if key in ports}
    parameters = {key: value for key, value in given.items() if key not in ports}
    known = set(spec.parameters.model_fields)
    unknown = sorted(set(parameters) - known)
    if unknown:
        raise TypeError(
            f"{block_id} has no input or parameter {', '.join(unknown)} (inputs: "
            f"{', '.join(sorted(ports)) or 'none'}; parameters: {', '.join(sorted(known)) or 'none'})"
        )
    data = {key: value for key, value in inputs.items() if isinstance(value, pd.Series)}
    signals = {key: str(value) for key, value in inputs.items() if isinstance(value, str)}
    signals.update({key: str(value.name or key) for key, value in data.items()})
    wired = dict(roles or {})
    if asset and not wired and not inputs:
        wired = {port.port_id: "pv" for port in spec.inputs if port.required}
    diagram, skipped = block_diagram(block_id, spec, wired, signals, parameters)
    missing = [port.port_id for port in spec.inputs if port.required and port.port_id in skipped]
    if missing:
        raise ValueError(
            f"Say where {', '.join(missing)} comes from: asset=... (with roles={{...}}), a "
            "signal id or a pandas Series."
        )
    keep = [("block", port.port_id) for port in spec.outputs]
    # A data quality check judges samples as recorded: read raw unless a step is given.
    reader = PlantReader(plant, raw=step is None and block_id.startswith(RAW_FIRST))
    if not data:
        if not asset and not signals:
            raise ValueError("Say what the block reads: asset=..., a signal id or a pandas Series.")
        begin, finish, seconds = _window(AssetTiming(), start, end, step, plant)
        ran = run_on_asset(
            diagram,
            asset or "notebook",
            client=reader if asset else _AnyAsset(reader),
            start=begin,
            end=finish,
            step=seconds,
            algorithm_id="notebook",
            keep=keep,
        )
        return _summary_run(ran, keep)
    # Series of the person's own: the window is what they cover.
    named: dict[str, Any] = {}
    for key, value in data.items():
        series = value.copy()
        index = pd.DatetimeIndex(series.index)
        series.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
        series.name = signals[key]
        named[f"in_{key}"] = pd.to_numeric(series, errors="coerce").sort_index()
    covered = pd.DatetimeIndex(pd.concat(list(named.values())).index)
    begin = pd.Timestamp(plant.moment(start)) if start is not None else covered.min()
    finish = pd.Timestamp(plant.moment(end)) if end is not None else covered.max()
    gaps = covered.sort_values().to_series().diff().dropna()
    seconds = float(step or (gaps.median().total_seconds() if not gaps.empty else 60.0) or 60.0)
    others = {key: signal for key, signal in signals.items() if key not in data}
    if others:
        columns, _ = reader.series_many_pandas(list(others.values()), begin, finish, seconds)
        for key, signal in others.items():
            found = columns.get(signal)
            named[f"in_{key}"] = (
                found if isinstance(found, pd.Series) else NoData(f"No data for {signal}.")
            )
    subject = reader.asset(asset) if asset else {"id": "notebook", "name": "notebook"}
    ran = _run_plan(
        _plan(diagram),
        str(subject.get("id") or "notebook"),
        subject,
        named,
        signals,
        start=begin,
        end=finish,
        step=seconds,
        algorithm_id="notebook",
        keep=keep,
    )
    return _summary_run(ran, keep)


class _AnyAsset:
    """A reader for a block whose inputs are all signal ids: no asset is read."""

    def __init__(self, reader: PlantReader):
        self.reader = reader

    def asset(self, asset_id: str) -> dict[str, Any]:
        return {"id": asset_id or "notebook", "name": "notebook", "signals": {}}

    def series_many_pandas(self, *args: Any) -> Any:
        return self.reader.series_many_pandas(*args)


def _loop_run(
    item: dict[str, Any], plant: Any, asset: str, start: Any, end: Any, step: float | None
) -> Run:
    """A loop's algorithm as Link's loop round runs it (``loops.analysis.analyze_loop``): the
    loop read from its asset record, its raw samples over the window, the loop's health."""

    from linkcraft.config import AnalysisConfig
    from linkcraft.data.frames import loop_signal_ids
    from linkcraft.loops.analysis import analyze_loop
    from linkcraft.loops.sync import loop_from_asset

    loop = loop_from_asset(PlantReader(plant).asset(asset), {})
    if loop is None or loop.incomplete:
        raise ValueError(f"{asset} is not a loop with its PV bound in PlantCraft.")
    analysis = AnalysisConfig(resample_seconds=int(step or AnalysisConfig().resample_seconds))
    finish = pd.Timestamp(plant.moment(end if end is not None else "now"))
    begin = (
        pd.Timestamp(plant.moment(start))
        if start is not None
        else finish - pd.Timedelta(minutes=analysis.window_minutes)
    )
    raw = plant.series(loop_signal_ids(loop), begin, finish)
    ran = analyze_loop(
        analysis, loop, raw, diagram=item.get("diagram") or {}, algorithm_id=str(item.get("id"))
    )
    summary = ran["summary"]
    verdict = {
        "status": summary.get("status"),
        "value": summary.get("health"),
        "message": summary.get("operating_state_reason") or summary.get("limiting") or "",
    }
    outputs = {
        str(result.get("method_id") or index): result.get("score")
        for index, result in enumerate(ran.get("results") or [])
    }
    window = {
        "start": begin.isoformat(),
        "end": finish.isoformat(),
        "step": analysis.resample_seconds,
    }
    return Run(outputs=outputs, verdict=verdict, window=window, summary=summary)


def run_algorithm(
    item: dict[str, Any],
    plant: Any,
    app: Any,
    *,
    asset: str,
    start: Any = None,
    end: Any = None,
    step: float | None = None,
) -> Run:
    """Run a whole algorithm on ``asset`` over its window (its own window and step unless
    ``start``, ``end`` or ``step`` say otherwise), as Link runs it: a loop's algorithm as the loop
    round does (its health, each method's score), any other on the asset as a schedule does
    (every recorded output, what it would publish and its verdict)."""

    diagram = item.get("diagram") or {}
    for node in diagram.get("nodes") or []:
        if isinstance(node, dict) and node.get("block"):
            _site_block(str(node["block"]), app)
    if (item.get("subject_kind") or "loop") == "loop":
        return _loop_run(item, plant, asset, start, end, step)
    plan = _plan(diagram)
    keep = [(node, port) for node, ports in plan.recorded.items() for port in ports]
    timing = timing_of({"timing": item.get("timing") or {}})
    begin, finish, seconds = _window(timing, start, end, step, plant)
    ran = run_on_asset(
        diagram,
        asset,
        client=PlantReader(plant),
        start=begin,
        end=finish,
        step=seconds,
        algorithm_id=str(item.get("id") or "notebook"),
        keep=keep,
    )
    return _summary_run(ran, keep)


def test_block(file: dict[str, Any] | str, **options: Any) -> Run:
    """Test a block file (``plantcraft-block/1``) that is not in Link yet, as Link's own test
    does: its contract read and its code checked, then run like ``run_block`` (the same
    options). Nothing is sent to Link."""

    import sys

    found = read_file(file)
    problems = sandbox.check_code(found.code)
    if problems:
        raise ValueError(" ".join(problems))
    block_id = site.draft_id(found)
    CATALOG[block_id] = site.code_block(found, block_id)
    return run_block({"block_id": block_id}, sys.modules["plantcraft_notebook"], None, **options)


def run(kind: str, item: dict[str, Any], plant: Any, app: Any, **options: Any) -> Run:
    """What ``plantcraft_notebook`` calls for ``.run(...)`` on one of Link's objects."""

    if kind == "block":
        return run_block(item, plant, app, **options)
    if kind == "algorithm":
        return run_algorithm(item, plant, app, **options)
    raise ValueError(f"Link runs blocks and algorithms, not {kind!r}.")


__all__ = ["PlantReader", "Run", "run", "run_algorithm", "run_block", "test_block"]
