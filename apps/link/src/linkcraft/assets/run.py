"""One run of an algorithm on one asset: read what its signal blocks ask for, run the diagram.

The signal blocks (``input.signal``, ``input.state``) name a role of the asset, a role of another
asset or a signal by its id; they are resolved through the asset records in PlantCraft and read
in one request, on the algorithm's step, over its window. Blocks keep their memory between runs
(``Context.states``: the deviation block's run of deviating cycles), which the caller stores.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import Context, NoData, Result, execute
from plantcraft_sdk.client import NotFound, PlantCraftError
from pydantic import BaseModel, Field, model_validator

from linkcraft.blocks import CATALOG, compile_algorithm
from linkcraft.blocks.run import block_verdicts, recorded_ports, samples, trace, wires
from linkcraft.i18n import t

INPUT_BLOCKS = ("input.signal", "input.state")
# Points a window may hold on its step (a day at five seconds is 17 280).
MAX_POINTS = 20_000
# Points of one recorded series a run sends to the historian at most.
MAX_RECORDED_POINTS = 2_000


class AssetTiming(BaseModel):
    """When an algorithm on assets runs and what it reads each time."""

    cycle_seconds: float = Field(
        default=60.0,
        ge=10,
        le=86_400,
        title="Every",
        description="How often the algorithm runs on each of its assets.",
        json_schema_extra={"unit": "s"},
    )
    window_seconds: float = Field(
        default=1_800.0,
        ge=60,
        le=7 * 86_400,
        title="Window",
        description="How far back each run reads, ending at the run's time.",
        json_schema_extra={"unit": "s"},
    )
    step_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=3_600,
        title="Step",
        description="The time step the signals are read on.",
        json_schema_extra={"unit": "s"},
    )

    @model_validator(mode="after")
    def _points(self) -> AssetTiming:
        if self.window_seconds / self.step_seconds > MAX_POINTS:
            raise ValueError(
                t("A window holds at most {count} steps: widen the step.", count=MAX_POINTS)
            )
        return self


def timing_of(config: dict[str, Any] | None) -> AssetTiming:
    """The timing an algorithm's stored configuration gives (defaults where it says nothing)."""

    try:
        return AssetTiming.model_validate((config or {}).get("timing") or {})
    except ValueError:
        return AssetTiming()


def window_end(now: pd.Timestamp, step: float) -> pd.Timestamp:
    """``now`` floored to the step, so consecutive runs read the same grid."""

    stamp = pd.Timestamp(now)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    seconds = stamp.timestamp()
    return pd.Timestamp(math.floor(seconds / step) * step, unit="s", tz="UTC")


class AssetReader:
    """Asset records and series through one PlantCraft client, records kept for one run."""

    def __init__(self, client: Any):
        self.client = client
        self._assets: dict[str, dict[str, Any]] = {}

    def asset(self, asset_id: str) -> dict[str, Any]:
        if asset_id not in self._assets:
            try:
                self._assets[asset_id] = dict(self.client.asset(asset_id))
            except NotFound as exc:
                raise LookupError(t("Asset {asset} is not in PlantCraft.", asset=asset_id)) from exc
            except PlantCraftError as exc:
                raise LookupError(
                    t(
                        "PlantCraft did not answer for asset {asset}: {why}",
                        asset=asset_id,
                        why=exc,
                    )
                ) from exc
        return self._assets[asset_id]

    def resolve(self, parameters: dict[str, Any], subject: dict[str, Any]) -> str:
        """The signal id a signal block reads: by id, or a role of the asset or of another."""

        signal = str(parameters.get("signal") or "").strip()
        if signal:
            return signal
        role = str(parameters.get("role") or "").strip()
        other = str(parameters.get("asset") or "").strip()
        asset = self.asset(other) if other else subject
        found = (asset.get("signals") or {}).get(role)
        if not found:
            raise LookupError(
                t(
                    "Asset {asset} has no signal for role {role} in PlantCraft.",
                    asset=asset.get("name") or asset.get("id"),
                    role=role,
                )
            )
        return str(found)


def _utc_index(series: pd.Series) -> pd.Series:
    index = pd.DatetimeIndex(series.index)
    series = series.copy()
    series.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    return series.sort_index()


def read_inputs(
    plan: Any,
    reader: AssetReader,
    subject: dict[str, Any],
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: float,
) -> tuple[dict[str, Any], dict[str, str]]:
    """What each signal block of ``plan`` reads, by node id (a series, or why there is none),
    and the signal id each one resolved to."""

    named: dict[str, Any] = {}
    wanted: dict[str, str] = {}
    for node_id, node in plan.nodes.items():
        if node.get("block") not in INPUT_BLOCKS:
            continue
        try:
            wanted[node_id] = reader.resolve(dict(node.get("parameters") or {}), subject)
        except LookupError as exc:
            named[node_id] = NoData(str(exc), node_id)
    if wanted:
        try:
            columns, errors = reader.client.series_many_pandas(
                sorted(set(wanted.values())), start.to_pydatetime(), end.to_pydatetime(), step
            )
            failed = {item["signal"]: str(item.get("detail") or "") for item in errors}
        except PlantCraftError as exc:
            columns, failed = {}, {signal: str(exc.detail or exc) for signal in wanted.values()}
        for node_id, signal in wanted.items():
            series = columns.get(signal)
            if not isinstance(series, pd.Series) or series.dropna().empty:
                reason = failed.get(signal) or t(
                    "No data for {signal} in the window.", signal=signal
                )
                named[node_id] = NoData(reason, node_id)
                continue
            series = _utc_index(series)
            if plan.nodes[node_id]["block"] == "input.signal":
                attrs = dict(series.attrs)
                series = pd.to_numeric(series, errors="coerce")
                series.attrs.update(attrs)  # "recorded": read as recorded, not as means
            series.name = signal
            named[node_id] = series
    return named, wanted


def _points(value: Any) -> dict[str, list[Any]] | None:
    if not isinstance(value, pd.Series):
        return None
    numbers = pd.to_numeric(value, errors="coerce").dropna().iloc[-MAX_RECORDED_POINTS:]
    if numbers.empty:
        return None
    index = pd.DatetimeIndex(numbers.index)
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    return {
        "t": [stamp.isoformat() for stamp in index],
        "v": [float(item) for item in numbers.to_numpy()],
    }


def overall(outputs: list[dict[str, Any]], blocks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The run's one verdict: its worst published result, else its worst block."""

    order = {"bad": 3, "warning": 2, "ok": 1, "unknown": 0}
    items = [item for item in outputs if item.get("kind") == "result"] or list(blocks.values())
    if not items:
        return {"status": "unknown", "value": None, "message": t("The algorithm gave no result.")}
    worst = max(items, key=lambda item: order.get(str(item.get("status")), 0))
    return {
        "status": str(worst.get("status") or "unknown"),
        "value": worst.get("value"),
        "message": str(worst.get("message") or ""),
        "name": worst.get("name") or worst.get("label") or "",
    }


def run_on_asset(
    diagram: dict[str, Any],
    asset_id: str,
    *,
    client: Any,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: float,
    models: Any = None,
    states: dict[str, dict[str, Any]] | None = None,
    algorithm_id: str | None = None,
    with_trace: bool = False,
    keep: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Run ``diagram`` on asset ``asset_id`` over ``start``-``end``.

    Returns the summary (outputs, each block's verdict, recorded ports with their points, the
    run's verdict), the blocks' memory after the run (``states``), for a test the trace, and the
    values of the ports in ``keep`` as they are (``kept``: what Calibrate gathers).
    ``LookupError`` when the asset itself cannot be read; ``ValueError`` for an invalid diagram.
    """

    plan = _plan(diagram)
    reader = AssetReader(client)
    subject = reader.asset(asset_id)
    named, signals = read_inputs(plan, reader, subject, start, end, step)
    return _run_plan(
        plan,
        asset_id,
        subject,
        named,
        signals,
        start=start,
        end=end,
        step=step,
        models=models,
        states=states,
        algorithm_id=algorithm_id,
        with_trace=with_trace,
        keep=keep,
    )


def block_diagram(
    block_id: str,
    spec: Any,
    roles: dict[str, str] | None = None,
    signals: dict[str, str] | None = None,
    parameters: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """One block alone in a diagram, each series or state input read from a role of the asset
    (``pv``, ``sp``…) or a signal id: what a block's test runs, in Link and in a notebook.

    Returns the diagram (the block is node ``block``, every output recorded) and the inputs left
    unwired (neither a role nor a signal, or not a series)."""

    roles, signals = roles or {}, signals or {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    skipped = []
    for port in spec.inputs:
        role = str(roles.get(port.port_id) or "").strip()
        signal = str(signals.get(port.port_id) or "").strip()
        source = (
            "input.state"
            if "state" in port.types and "series" not in port.types
            else "input.signal"
        )
        if not (role or signal) or not ({"series", "state"} & set(port.types)):
            skipped.append(port.port_id)
            continue
        node_id = f"in_{port.port_id}"
        node_parameters: dict[str, Any] = {
            "role": role or ("mode" if source == "input.state" else "pv")
        }
        if signal and source == "input.signal":
            node_parameters["signal"] = signal
        nodes.append({"id": node_id, "block": source, "parameters": node_parameters})
        edges.append(
            {
                "source": node_id,
                "source_port": "value",
                "target": "block",
                "target_port": port.port_id,
            }
        )
    nodes.append(
        {
            "id": "block",
            "block": block_id,
            "parameters": dict(parameters or {}),
            "record": [port.port_id for port in spec.outputs],
        }
    )
    return {"nodes": nodes, "edges": edges}, skipped


def segment_ends(start: pd.Timestamp, end: pd.Timestamp, stride: float) -> list[pd.Timestamp]:
    """Run ends laid one ``stride`` apart over ``start``-``end``: the first a stride after
    ``start``, so the judged parts of the runs cover the period end to end."""

    ends, moment = [], start + pd.Timedelta(seconds=stride)
    while moment <= end:
        ends.append(moment)
        moment += pd.Timedelta(seconds=stride)
    return ends


def runs_over(
    diagram: dict[str, Any],
    asset_id: str,
    *,
    client: Any,
    ends: list[pd.Timestamp],
    window: float,
    step: float,
    models: Any = None,
    states: dict[str, dict[str, Any]] | None = None,
    algorithm_id: str | None = None,
    keep: list[tuple[str, str]] | None = None,
) -> Iterator[dict[str, Any]]:
    """The runs of ``diagram`` on ``asset_id`` ending at each of ``ends``, as the cycle would
    have made them (the blocks' memory carried from one to the next), reading the plant once.
    What Calibrate and a replay over a past period use."""

    if not ends:
        return
    plan = _plan(diagram)
    reader = AssetReader(client)
    subject = reader.asset(asset_id)
    span = pd.Timedelta(seconds=window)
    named, signals = read_inputs(plan, reader, subject, ends[0] - span, ends[-1], step)
    memory = {key: dict(value) for key, value in (states or {}).items()}
    for moment in ends:
        found = _run_plan(
            plan,
            asset_id,
            subject,
            _sliced(named, moment - span, moment),
            signals,
            start=moment - span,
            end=moment,
            step=step,
            models=models,
            states=memory,
            algorithm_id=algorithm_id,
            keep=keep,
        )
        memory = found["states"]
        yield found


def _plan(diagram: dict[str, Any]) -> Any:
    plan = compile_algorithm(diagram)
    if not plan.valid:
        raise ValueError(t("Invalid algorithm: {errors}", errors=" ".join(plan.errors)))
    return plan


def _sliced(named: dict[str, Any], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    """What each signal block read, cut to one run's window."""

    cut: dict[str, Any] = {}
    for node_id, value in named.items():
        if not isinstance(value, pd.Series):
            cut[node_id] = value
            continue
        part = value[(value.index >= start) & (value.index <= end)]
        cut[node_id] = (
            part
            if not part.dropna().empty
            else NoData(t("No data for {signal} in the window.", signal=value.name), node_id)
        )
    return cut


def _run_plan(
    plan: Any,
    asset_id: str,
    subject: dict[str, Any],
    named: dict[str, Any],
    signals: dict[str, str],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: float,
    models: Any = None,
    states: dict[str, dict[str, Any]] | None = None,
    algorithm_id: str | None = None,
    with_trace: bool = False,
    keep: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    context = Context(
        start=start,
        end=end,
        sample_seconds=float(step),
        asset={"id": asset_id, "name": subject.get("name") or asset_id},
        extra={"named": named, "models": models},
        states={key: dict(value) for key, value in (states or {}).items()},
    )
    values = execute(plan, CATALOG, context)
    collected = context.extra.get("collected") or {}
    outputs = list(collected.get("outputs") or [])
    blocks = block_verdicts(plan, values)
    recorded = recorded_ports(plan, values)
    for entry in recorded:
        if entry.get("type") == "series":
            points = _points(values.get(entry["node_id"], entry["port"]))
            if points:
                entry["points"] = points
    summary = {
        "algorithm": algorithm_id,
        "outputs": outputs,
        "blocks": blocks,
        "recorded": recorded,
        "verdict": overall(outputs, blocks),
        "wires": wires(plan, values),
        "samples": samples(plan, values),
        "signals": signals,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "step": float(step)},
        # Message outputs are tracked per algorithm, so two on one asset never close each other's.
        "message_scope": f"{algorithm_id or 'test'}.",
    }
    payload: dict[str, Any] = {
        "asset": {"id": asset_id, "name": subject.get("name") or asset_id},
        "config": {"name": subject.get("name") or asset_id},
        "summary": summary,
        "states": context.states,
    }
    if with_trace:
        payload["trace"] = trace(plan, values)
    if keep:
        payload["kept"] = {(node, port): values.get(node, port) for node, port in keep}
    return payload


def failed_summary(algorithm_id: str, reason: str) -> dict[str, Any]:
    """The summary of a run that could not start (the asset unreadable, the diagram invalid)."""

    return {
        "algorithm": algorithm_id,
        "outputs": [],
        "blocks": {},
        "recorded": [],
        "verdict": Result.unknown(reason).as_dict(),
    }


__all__ = [
    "AssetReader",
    "AssetTiming",
    "block_diagram",
    "failed_summary",
    "overall",
    "read_inputs",
    "run_on_asset",
    "runs_over",
    "segment_ends",
    "timing_of",
    "window_end",
]
