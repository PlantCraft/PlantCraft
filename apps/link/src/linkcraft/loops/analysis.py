"""Analysis of one control loop: its algorithm's diagram run on the loop's window.

Everything here is a pure function of the loop, its raw samples, the algorithm and the analysis
settings. The monitor runs ``analyze_loop_task`` in worker processes so a portfolio of thousands
of loops uses every CPU core. What runs is exactly the diagram (``linkcraft.blocks``): the loop
data check, the methods and the outputs are blocks in it.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import Context, NoData, Plan, Result, Values, execute
from plantcraft_sdk.methods import DataQuality, LoopDataset, MethodResult
from plantcraft_sdk.methods.utils import insufficient_data

from linkcraft.blocks import CATALOG, GATE_ID, HEALTH_ID, compile_algorithm, method_of
from linkcraft.blocks.convert import diagram_of, from_methods
from linkcraft.blocks.health import (  # noqa: F401 (kept importable from here)
    SATURATED_TRACKING_RATIO,
    _json_result,
    _last_numeric,
    _manual_fraction,
    _operating_state,
    loop_summary,
)
from linkcraft.blocks.run import (  # noqa: F401 (kept importable from here)
    TRACE_POINTS,
    samples,
    trace,
    wires,
)
from linkcraft.blocks.run import block_verdicts as _blocks
from linkcraft.blocks.run import recorded_ports as _recorded
from linkcraft.catalog.registry import get_method_spec
from linkcraft.config import AnalysisConfig, LoopConfig
from linkcraft.data.frames import build_loop_frame, semantic_raw
from linkcraft.i18n import t

logger = logging.getLogger(__name__)

CRITICALITY_WEIGHTS = {"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.6}


def loop_priority(health: float | None, criticality: str) -> float | None:
    """Ranking score: points lost from 100, weighted by the loop's criticality."""

    if health is None:
        return None
    weight = CRITICALITY_WEIGHTS.get(criticality, 1.0)
    return round(max(0.0, 100.0 - float(health)) * weight, 1)


def _overrides(
    analysis: AnalysisConfig,
    loop: LoopConfig,
    parameter_overrides: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Method parameters over the diagram's: the run's own when given, else site then loop."""

    if parameter_overrides is not None:
        return parameter_overrides
    merged: dict[str, dict[str, Any]] = {}
    for layer in (analysis.method_parameters, loop.method_parameters):
        for method_id, values in layer.items():
            merged.setdefault(method_id, {}).update(values)
    return merged


def _dataset(
    analysis: AnalysisConfig, loop: LoopConfig, frame: pd.DataFrame, raw: Any
) -> LoopDataset:
    valid = (
        float(pd.to_numeric(frame.get("pv"), errors="coerce").notna().mean()) if len(frame) else 0.0
    )
    return LoopDataset(
        loop_id=loop.loop_id,
        data=pd.DataFrame(),
        sample_time_seconds=analysis.resample_seconds,
        start_time=(str(frame["timestamp"].min()) if len(frame) else None),
        end_time=(str(frame["timestamp"].max()) if len(frame) else None),
        quality=DataQuality(valid_fraction=valid, missing_fraction=1.0 - valid),
        raw=raw,
        metadata={
            "name": loop.name,
            "area": loop.area,
            "service": loop.service,
            "unit": loop.unit,
            # What the asset record says the loop is (methods that apply to one kind read it).
            "loop_type": loop.asset_record.loop_type if loop.asset_record else None,
        },
    )


def _results(plan: Plan, values: Values, loop: LoopConfig) -> list[dict[str, Any]]:
    """Every method's result in run order: the loop data check's, then the CPM blocks'."""

    found: list[dict[str, Any]] = []
    for node_id in plan.order:
        block = plan.nodes[node_id]["block"]
        if block == GATE_ID:
            verdict = values.get(node_id, "verdict")
            if isinstance(verdict, Result):
                found += [
                    _json_result(item)
                    for item in verdict.detail.get("results") or []
                    if isinstance(item, MethodResult)
                ]
            continue
        method_id = method_of(block)
        if not method_id:
            continue
        verdict = values.get(node_id, "result")
        if isinstance(verdict, Result) and isinstance(verdict.detail.get("method"), MethodResult):
            found.append(_json_result(verdict.detail["method"]))
        else:
            reason = verdict.reason if isinstance(verdict, NoData) else t("The method did not run.")
            found.append(
                _json_result(
                    insufficient_data(get_method_spec(method_id).metadata, loop.loop_id, reason)
                )
            )
    return found


def analyze_loop(
    analysis: AnalysisConfig,
    loop: LoopConfig,
    raw: pd.DataFrame,
    *,
    diagram: dict[str, Any] | None = None,
    method_ids: list[str] | None = None,
    parameter_overrides: dict[str, dict[str, Any]] | None = None,
    parameter_defaults: dict[str, dict[str, Any]] | None = None,
    flow: dict[str, Any] | None = None,
    external_quality: dict[str, Any] | None = None,
    algorithm_id: str | None = None,
    with_trace: bool = False,
) -> dict[str, Any]:
    """Run one loop's algorithm on its raw samples: summary, results and frame.

    ``diagram`` is the algorithm (an old protocol's ``flow`` or ``method_ids`` are converted,
    ``blocks.convert``). ``external_quality`` is the Signal quality algorithm's word on the
    loop's signals (``loops/suite.py``, ``quality_verdicts``), which the loop data check reads.
    Method parameters layer as ``parameter_defaults`` < the diagram's < ``parameter_overrides``.
    """

    if diagram is None:
        diagram = (
            diagram_of({"flow": flow})
            if flow
            else from_methods(method_ids or loop.enabled_methods or analysis.enabled_methods)
        )
    frame = build_loop_frame(raw, loop, analysis.resample_seconds)
    plan = compile_algorithm(
        diagram, _overrides(analysis, loop, parameter_overrides), defaults=parameter_defaults
    )
    if not plan.valid:
        raise ValueError(t("Invalid algorithm: {errors}", errors=" ".join(plan.errors)))
    roles = semantic_raw(raw, loop)
    stamps = pd.to_datetime(frame["timestamp"], errors="coerce") if len(frame) else None
    start = raw.index.min() if len(raw.index) else (stamps.min() if stamps is not None else None)
    end = raw.index.max() if len(raw.index) else (stamps.max() if stamps is not None else None)
    external = external_quality or {}
    context = Context(
        start=start,
        end=end,
        sample_seconds=float(analysis.resample_seconds),
        asset={"id": loop.loop_id, "name": loop.name},
        extra={
            "frame": frame,
            "raw": roles,
            "roles": {role for role, signal in loop.signals.model_dump().items() if signal},
            "dataset": _dataset(analysis, loop, frame, roles),
            "analysis": analysis,
            "external_quality": external,
            "verdicts": external.get("roles") or {},
            "unit": loop.unit,
            "health_excluded": list(loop.health_excluded_methods),
        },
    )
    values = execute(plan, CATALOG, context)
    collected = context.extra.get("collected") or {}
    results = _results(plan, values, loop)
    health = collected.get("health")
    gates = [node_id for node_id in plan.order if plan.nodes[node_id]["block"] == GATE_ID]
    gate = values.get(gates[0], "verdict") if gates else None
    detail = gate.detail if isinstance(gate, Result) else {}
    cpm = any(method_of(node["block"]) for node in plan.nodes.values())
    if health:
        summary = dict(health["summary"])
    else:
        summary = loop_summary(frame, [])
        summary.update(
            status="no_score",
            health=None,
            limiting=None,
            alerts=[],
            operating_state_reason=t("This algorithm gives no loop health; see its outputs."),
        )
    summary["method_count"] = len(results)
    summary["blocks"] = _blocks(plan, values)
    summary["wires"] = wires(plan, values)
    summary["samples"] = samples(plan, values)
    summary["outputs"] = collected.get("outputs") or []
    summary["recorded"] = _recorded(plan, values)
    if algorithm_id:
        summary["algorithm"] = algorithm_id
    summary["data_quality"] = {
        "apt": bool(detail.get("apt", True)),
        "reasons": list(detail.get("reasons") or []),
        "checked": bool(detail.get("checked", False)),
        "source": detail.get("source") or ("gate" if gates else "none"),
    }
    if gates and not cpm and not health:
        # The loop data check alone: a data quality run.
        reasons = summary["data_quality"]["reasons"]
        summary.update(
            kind="data_quality",
            status="no_data" if reasons else "normal",
            health=None,
            functional_score=None,
            functional_components=[],
            limiting=None,
            alerts=[],
        )
    payload = {
        "config": loop.model_dump(mode="json"),
        "summary": summary,
        "results": results,
        "frame": frame,
    }
    if with_trace:
        payload["trace"] = trace(plan, values)
    return payload


def analyze_loop_task(task: dict[str, Any]) -> dict[str, Any]:
    """Worker-process entry point: plain data in, summary and results out (no frame)."""

    payload = analyze_loop(
        AnalysisConfig.model_validate(task["analysis"]),
        LoopConfig.model_validate(task["loop"]),
        task["raw"],
        diagram=task.get("diagram"),
        method_ids=task.get("method_ids"),
        parameter_overrides=task.get("parameter_overrides"),
        parameter_defaults=task.get("parameter_defaults"),
        flow=task.get("flow"),
        external_quality=task.get("external_quality"),
        algorithm_id=task.get("algorithm_id"),
    )
    payload.pop("frame", None)
    return payload


__all__ = [
    "CRITICALITY_WEIGHTS",
    "HEALTH_ID",
    "analyze_loop",
    "analyze_loop_task",
    "loop_priority",
    "loop_summary",
    "trace",
]
