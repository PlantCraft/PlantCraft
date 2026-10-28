"""Control loop performance blocks (``cpm.*``) and the loop data check (``dq.loop_data``).

Each CPM method of ``linkcraft.methods`` becomes one block: its input ports become typed
inputs (series, or state for the mode), its verdict the ``result`` output and its metrics
numeric outputs. The texts come from the method's help page (``methods/help/<id>.md``) and its
metadata, so the block, the help and the assistant say the same.

The three loop gate methods (availability, value integrity, statistics) are one block,
``dq.loop_data``: it passes the loop's signals on only when the data is fit for analysis, so the
blocks after it run on usable data and, otherwise, say why they did not run.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import (
    Block,
    BlockDocs,
    BlockSpec,
    NoData,
    Port,
    Result,
    inport,
    outport,
)
from plantcraft_sdk.methods import LoopDataset, MethodResult
from plantcraft_sdk.methods.utils import insufficient_data

from linkcraft.blocks.base import ROLES, described, merged_model
from linkcraft.catalog.help import _page, documented_parameters
from linkcraft.catalog.help_docs import _reference
from linkcraft.catalog.labels import METHOD_LABELS
from linkcraft.catalog.registry import (
    METHOD_MODULES,
    METHOD_SPECS,
    describe_result,
    gate_method_ids,
    method_group,
)
from linkcraft.i18n import t

# The palette's group of each CPM block.
GROUPS = {
    "error_metrics_basic": "Tracking",
    "pv_variability": "Tracking",
    "harris_index": "Tracking",
    "op_saturation_fraction": "Valve and output",
    "op_travel_reversal": "Valve and output",
    "stiction_screening": "Valve and output",
    "oscillation_autocorrelation": "Oscillation and noise",
    "sensor_noise_ratio": "Oscillation and noise",
    "interaction_cross_correlation": "Oscillation and noise",
    "manual_mode_fraction": "Operation",
    "setpoint_activity": "Operation",
    "operational_interventions": "Operation",
    "sampling_quality": "Data",
    "disturbance_attenuation": "Surge level",
    "operating_band_fraction": "Surge level",
}

# What each numeric output of a method means: label, description, unit, which way is better.
METRICS: dict[tuple[str, str], tuple[str, str, str, str | None]] = {
    ("error_metrics_basic", "mae"): (
        "MAE",
        "Mean absolute error between setpoint and PV over the window, in the PV's unit.",
        "",
        "lower",
    ),
    ("error_metrics_basic", "rmse"): (
        "RMSE",
        "Root mean square error between setpoint and PV, in the PV's unit; large errors weigh "
        "more.",
        "",
        "lower",
    ),
    ("error_metrics_basic", "iae"): (
        "IAE",
        "Integral of the absolute error over the window, in the PV's unit times seconds.",
        "",
        "lower",
    ),
    ("error_metrics_basic", "ise"): (
        "ISE",
        "Integral of the squared error over the window: large, lasting errors dominate it.",
        "",
        "lower",
    ),
    ("error_metrics_basic", "itae"): (
        "ITAE",
        "Integral of the absolute error weighted by time: errors that last weigh more.",
        "",
        "lower",
    ),
    ("error_metrics_basic", "within_band_fraction"): (
        "Time in band",
        "Share of the window, from 0 to 1, with the PV inside the acceptable band around the SP.",
        "",
        "higher",
    ),
    ("operational_interventions", "sp_changes"): (
        "SP changes",
        "How many times operators moved the setpoint in the window.",
        "",
        "lower",
    ),
    ("operational_interventions", "mode_switches"): (
        "Mode switches",
        "How many times the controller's mode changed in the window.",
        "",
        "lower",
    ),
    ("operational_interventions", "interventions_reference_window"): (
        "Interventions per reference window",
        "Setpoint changes and mode switches scaled to the reference window (12 h by default).",
        "",
        "lower",
    ),
    ("operational_interventions", "performance_component"): (
        "Score",
        "This criterion's score from 0 to 100: 100 with few interventions, 0 with many.",
        "/100",
        "higher",
    ),
    ("disturbance_attenuation", "amplification_factor"): (
        "Amplification factor",
        "How much the output's movement amplifies the level's: below 1 the level absorbs the "
        "disturbance, above 1 the loop passes it on.",
        "",
        "lower",
    ),
    ("disturbance_attenuation", "performance_component"): (
        "Score",
        "This criterion's score from 0 to 100: 100 when the level absorbs the disturbances.",
        "/100",
        "higher",
    ),
    ("operating_band_fraction", "inside_fraction"): (
        "Time in band",
        "Share of the window, from 0 to 1, with the level inside its operating band.",
        "",
        "higher",
    ),
    ("operating_band_fraction", "performance_component"): (
        "Score",
        "This criterion's score from 0 to 100: 100 when the level stays inside its band.",
        "/100",
        "higher",
    ),
    ("sampling_quality", "median_sample_seconds"): (
        "Median sample interval",
        "Median time between the recorded samples, in seconds.",
        "s",
        "lower",
    ),
    ("sampling_quality", "gap_count"): (
        "Gaps",
        "How many intervals between samples are much longer than the median one.",
        "",
        "lower",
    ),
    ("pv_variability", "score"): (
        "Variability score",
        "How much the PV varies against the tolerance, from 0 (steady) to 100 (very variable).",
        "/100",
        "lower",
    ),
    ("manual_mode_fraction", "manual_fraction"): (
        "Time in manual",
        "Share of the window, from 0 to 1, with the controller in manual.",
        "",
        "lower",
    ),
    ("op_saturation_fraction", "saturation_fraction"): (
        "Time saturated",
        "Share of the window, from 0 to 1, with the output at its lower or upper limit.",
        "",
        "lower",
    ),
    ("setpoint_activity", "changes_per_hour"): (
        "SP changes per hour",
        "How many setpoint moves per hour the window had.",
        "1/h",
        None,
    ),
    ("setpoint_activity", "total_abs_change"): (
        "Total SP change",
        "Sum of the sizes of all setpoint moves in the window, in the PV's unit.",
        "",
        None,
    ),
    ("oscillation_autocorrelation", "autocorrelation_peak"): (
        "Autocorrelation peak",
        "Height of the first autocorrelation peak, from 0 to 1: how strongly the signal repeats.",
        "",
        "lower",
    ),
    ("oscillation_autocorrelation", "dominant_period_seconds"): (
        "Oscillation period",
        "Period of the cycle the autocorrelation found, in seconds.",
        "s",
        None,
    ),
    ("sensor_noise_ratio", "noise_ratio"): (
        "Noise ratio",
        "Share of the measurement's total variation that is high-frequency noise, from 0 to 1.",
        "",
        "lower",
    ),
    ("op_travel_reversal", "travel_per_hour"): (
        "Travel per hour",
        "Accumulated output movement per hour, in percent: the wear on the actuator.",
        "%/h",
        "lower",
    ),
    ("op_travel_reversal", "reversals_per_hour"): (
        "Reversals per hour",
        "How many times per hour the output changed direction.",
        "1/h",
        "lower",
    ),
    ("stiction_screening", "stiction_score"): (
        "Stiction index",
        "How strongly the output shows stick-then-slip while the PV cycles, from 0 to 100.",
        "/100",
        "lower",
    ),
    ("stiction_screening", "op_flat_fraction"): (
        "Stuck moves",
        "Share of the output's moves, from 0 to 1, too small to move the valve (stuck).",
        "",
        "lower",
    ),
    ("stiction_screening", "op_jump_fraction"): (
        "Slip jumps",
        "Share of the output's moves, from 0 to 1, that jump right after a stuck move (slip).",
        "",
        "lower",
    ),
    ("interaction_cross_correlation", "max_abs_correlation"): (
        "Correlation",
        "Largest correlation, from 0 to 1, between this loop's PV and the other signal.",
        "",
        "lower",
    ),
    ("interaction_cross_correlation", "best_lag_seconds"): (
        "Lag",
        "Time shift, in seconds, at which the two signals correlate the most.",
        "s",
        None,
    ),
    ("harris_index", "score"): (
        "Variance score",
        "How far the loop's variance is above minimum-variance control, from 0 to 100.",
        "/100",
        "lower",
    ),
}

RESULT_TEXT = (
    "The method's verdict on the window: status, a score from 0 to 100 (100 is best) and one "
    "sentence that explains it."
)
TIMESTAMP_PORT = (
    "Any recorded signal of the loop (the PV as recorded, usually): only the times of its "
    "samples are read."
)


def block_id(method_id: str) -> str:
    return f"cpm.{method_id}"


def _section_text(page: dict[str, Any] | None, section_id: str) -> tuple[str, list[str]]:
    """A help page section as paragraphs (joined) and list items."""

    paragraphs: list[str] = []
    items: list[str] = []
    for section in (page or {}).get("sections", []):
        if section["id"] != section_id:
            continue
        for block in section["blocks"]:
            if block["type"] == "p":
                paragraphs.append(block["text"])
            else:
                items.extend(block.get("items", []))
    return "\n\n".join(paragraphs), items


def _parameter_texts(method_id: str, page: dict[str, Any] | None) -> dict[str, tuple[str, str]]:
    from linkcraft.catalog.labels import PARAMETER_LABELS

    documented = documented_parameters(page) if page else {}
    texts = {}
    for key in METHOD_SPECS[method_id].parameter_schema.model_fields:
        title, fallback = PARAMETER_LABELS.get(key, (key.replace("_", " ").capitalize(), ""))
        meaning = (documented.get(key) or {}).get("meaning") or fallback
        texts[key] = (title, meaning[:1].upper() + meaning[1:])
    return texts


def method_docs(method_id: str) -> BlockDocs:
    spec = METHOD_SPECS[method_id]
    meta = spec.metadata
    page = _page(method_id)
    detects, detected = _section_text(page, "detects")
    reading, read_items = _section_text(page, "reading")
    _, limits = _section_text(page, "limits")
    description = "\n\n".join([detects, *(f"- {item}" for item in detected)]).strip()
    return BlockDocs(
        summary=meta.description,
        description=description or meta.description,
        reading="\n\n".join([reading, *(f"- {item}" for item in read_items)]).strip(),
        assumptions=tuple(meta.assumptions),
        limitations=tuple(limits or meta.limitations),
        formula=meta.implemented_formula or "",
        references=tuple(
            _reference(item.model_dump(mode="json") if hasattr(item, "model_dump") else item)
            for item in meta.references
        ),
    )


def _input_ports(method_id: str) -> tuple[Port, ...]:
    ports = []
    for port in METHOD_SPECS[method_id].input_ports:
        if port.port_id == "timestamp":
            ports.append(inport("x", "series", "Signal", TIMESTAMP_PORT))
            continue
        label, text = ROLES.get(port.port_id, (port.port_id, port.description or ""))
        kind = "state" if str(port.dtype).endswith("string") else "series"
        ports.append(
            inport(
                port.port_id,
                kind,
                label,
                text if len(text) >= 15 else f"{label}: {text or port.port_id}",
                required=port.required,
                unit="%" if port.unit == "percent" else "",
            )
        )
    return tuple(ports)


def _output_ports(method_id: str) -> tuple[Port, ...]:
    ports = [outport("result", "result", "Verdict", RESULT_TEXT)]
    for port in METHOD_SPECS[method_id].output_ports:
        label, text, unit, better = METRICS.get(
            (method_id, port.port_id),
            (
                port.port_id.replace("_", " ").capitalize(),
                f"The method's {port.port_id.replace('_', ' ')} over the window.",
                "",
                None,
            ),
        )
        ports.append(outport(port.port_id, "number", label, text, unit=unit, better=better))
    return tuple(ports)


def method_result(item: MethodResult | None, label: str) -> Result:
    """A method's result as a block verdict (score 100 is best)."""

    if item is None:
        return Result.unknown(t("The method did not run."), label)
    data = item.model_dump(mode="json")
    message = describe_result(data)
    status = str(data.get("status") or "")
    if status not in {"ok", "warning", "bad"}:
        return Result("unknown", None, message, label, {"method": item})
    component = (data.get("metrics") or {}).get("performance_component")
    if isinstance(component, (int, float)):
        value: float | None = float(component)
    else:
        try:
            value = 100.0 - float(data.get("score"))
        except (TypeError, ValueError):
            value = None
    return Result(status, value, message, label, {"method": item})


def frame_of(inputs: dict[str, Any]) -> pd.DataFrame:
    """The method's frame: ``timestamp`` plus one column per wired series."""

    columns = {
        port: value
        for port, value in inputs.items()
        if isinstance(value, pd.Series) and port != "x"
    }
    if not columns:
        stamps = inputs.get("x")
        index = stamps.index if isinstance(stamps, pd.Series) else pd.DatetimeIndex([])
        frame = pd.DataFrame(index=index)
    else:
        frame = pd.concat(columns, axis=1).sort_index()
    frame.insert(0, "timestamp", frame.index)
    return frame.reset_index(drop=True)


def base_dataset(ctx: Any) -> LoopDataset:
    found = ctx.extra.get("dataset")
    if isinstance(found, LoopDataset):
        return found
    # On an asset (an algorithm's run, a block's test, a notebook) no loop round prepared one:
    # the method reads the frame of its wired inputs (``run_method``).
    return LoopDataset(loop_id=str(ctx.asset.get("id", "")), data=pd.DataFrame())


def run_method(
    method_id: str, inputs: dict[str, Any], parameters: dict[str, Any], ctx: Any
) -> MethodResult:
    """One method on its wired inputs; a method that fails says so in its result."""

    spec = METHOD_SPECS[method_id]
    base = base_dataset(ctx)
    update: dict[str, Any] = {"data": frame_of(inputs)}
    if isinstance(inputs.get("x"), pd.Series):
        # Sampling quality reads the times of the signal wired to it.
        update["raw"] = pd.DataFrame({"pv": inputs["x"]})
    kwargs: dict[str, Any] = {"dataset": base.model_copy(update=update)}
    if method_id == "oscillation_autocorrelation" and isinstance(inputs.get("sp"), pd.Series):
        kwargs["signal"] = "error"
    if method_id == "interaction_cross_correlation":
        kwargs["secondary_column"] = "secondary"
    try:
        return METHOD_MODULES[method_id].run(
            spec.input_schema(**kwargs), spec.parameter_schema(**parameters)
        )
    except (Exception, SystemExit) as exc:  # A method calling exit() must not end the round.
        return insufficient_data(
            spec.metadata,
            base.loop_id,
            t("Run failed: {error}", error=f"{type(exc).__name__}: {exc}"),
        )


def _method_block(method_id: str) -> Block:
    spec = METHOD_SPECS[method_id]
    page = _page(method_id)
    parameters = described(
        spec.parameter_schema, _parameter_texts(method_id, page), f"{method_id}_parameters"
    )
    name = METHOD_LABELS.get(method_id) or spec.metadata.name
    outputs = _output_ports(method_id)

    def run(inputs: dict[str, Any], values: Any, ctx: Any) -> dict[str, Any]:
        item = run_method(method_id, inputs, values.model_dump(), ctx)
        verdict = method_result(item, name)
        metrics = item.metrics or {}
        given: dict[str, Any] = {"result": verdict}
        for port in outputs[1:]:
            value = metrics.get(port.port_id)
            if value is None and port.port_id == "score" and item.score is not None:
                value = item.score
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                given[port.port_id] = float(value)
            else:
                given[port.port_id] = NoData(
                    t(
                        "{block} gave no {port} this run: {why}",
                        block=name,
                        port=port.port_id,
                        why=verdict.message,
                    ),
                    ctx.node_id,
                )
        return given

    return Block(
        BlockSpec(
            block_id(method_id),
            spec.version,
            "cpm",
            name,
            method_docs(method_id),
            inputs=_input_ports(method_id),
            outputs=outputs,
            parameters=parameters,
            group=GROUPS.get(method_id, "Other"),
        ),
        run,
    )


# The loop data check ----------------------------------------------------------------

GATE_ID = "dq.loop_data"
PASSED = ("pv", "sp", "op", "mode")


@lru_cache(maxsize=1)
def gate_parameters() -> type:
    models = []
    for method_id in gate_method_ids():
        models.append(
            described(
                METHOD_SPECS[method_id].parameter_schema,
                _parameter_texts(method_id, _page(method_id)),
            )
        )
    return merged_model("LoopDataParameters", *models)


def _gate_run(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    analysis = ctx.extra.get("analysis")
    external = ctx.extra.get("external_quality") or {}
    blocked = [str(item) for item in external.get("blocked") or []]
    covered = external.get("covered") is True
    values = parameters.model_dump()
    results: list[MethodResult] = []
    if blocked or covered:
        source, checked, reasons = "signal_quality", True, blocked
    elif analysis is None or getattr(analysis, "data_quality_gate", True):
        source, checked = "gate", True
        for method_id in gate_method_ids():
            fields = METHOD_SPECS[method_id].parameter_schema.model_fields
            results.append(
                run_method(
                    method_id,
                    {port: inputs.get(port) for port in PASSED},
                    {key: value for key, value in values.items() if key in fields},
                    ctx,
                )
            )
        reasons = [item.message for item in results if item.metrics.get("apt") is False]
    else:
        source, checked, reasons = "gate", False, []
    detail = {
        "apt": not reasons,
        "reasons": reasons,
        "checked": checked,
        "source": source,
        "results": results,
    }
    name = t("Loop data check")
    if reasons:
        why = NoData(
            t("Not run: data not usable. {reasons}", reasons=" ".join(reasons)), ctx.node_id
        )
        given: dict[str, Any] = {port: why for port in PASSED}
        given["verdict"] = Result("bad", 0.0, " ".join(reasons), name, detail)
        return given
    given = {
        port: inputs[port]
        if inputs.get(port) is not None
        else NoData(t("Nothing is wired to {port}.", port=port.upper()), ctx.node_id)
        for port in PASSED
    }
    if not checked:
        message = t("The loop data check is switched off: the data was not checked.")
        given["verdict"] = Result("unknown", None, message, name, detail)
    elif source == "signal_quality":
        message = t("The Signal quality algorithm judged every signal of the loop usable.")
        given["verdict"] = Result("ok", 100.0, message, name, detail)
    else:
        message = t("The loop's data is fit for analysis.")
        given["verdict"] = Result("ok", 100.0, message, name, detail)
    return given


def _gate_block() -> Block:
    def checked(port: str, kind: str) -> Port:
        label, _text = ROLES[port]
        return outport(
            port,
            kind,
            label,
            f"The {label} passed on when the data is fit for analysis; no value (with the "
            "reason) when it is not.",
        )

    return Block(
        BlockSpec(
            GATE_ID,
            "1.0",
            "dq",
            "Loop data check",
            BlockDocs(
                summary="Passes a loop's signals on only when the window's data is fit for "
                "analysis.",
                description=(
                    "Checks the loop's data before any performance block reads it: enough PV "
                    "samples without long gaps (availability), no invalid, impossible or frozen "
                    "values (value integrity) and the window's statistics. When the Signal "
                    "quality algorithm has a fresh verdict on every signal of the loop, or has "
                    "blocked one, its word decides instead. Usable data passes through "
                    "unchanged; otherwise every output carries no value and the reason, so the "
                    "blocks after it report 'not run' instead of judging bad data."
                ),
                reading=(
                    "Ok: the data is usable and the blocks after it ran. Bad: the data is not "
                    "usable; the sentence says why (a gap, a frozen PV, a bad signal verdict) "
                    "and the loop gets no health this run. Unknown: the check is switched off."
                ),
                assumptions=("The PV is the signal whose availability decides.",),
                limitations=(
                    "It judges the window as a whole: a short bad stretch inside a long good "
                    "window passes.",
                ),
            ),
            inputs=(
                inport("pv", "series", "PV", ROLES["pv"][1]),
                inport("sp", "series", "SP", ROLES["sp"][1], required=False),
                inport("op", "series", "OP", ROLES["op"][1], required=False),
                inport("mode", "state", "Mode", ROLES["mode"][1], required=False),
            ),
            outputs=(
                checked("pv", "series"),
                checked("sp", "series"),
                checked("op", "series"),
                checked("mode", "state"),
                outport(
                    "verdict",
                    "result",
                    "Verdict",
                    "Whether the loop's data is fit for analysis, and why not.",
                ),
            ),
            parameters=gate_parameters(),
            group="Loops",
        ),
        _gate_run,
    )


def cpm_method_ids() -> list[str]:
    return [method_id for method_id in METHOD_SPECS if method_group(method_id) == "cpm"]


BLOCKS = (_gate_block(), *(_method_block(method_id) for method_id in cpm_method_ids()))
