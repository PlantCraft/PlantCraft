"""A PlantCraft Twin twin as an algorithm on assets: the same model, wiring and judgement.

A twin named one FMU, the plant signal behind each of its inputs and outputs (a signal id, or an
asset and a role, each with a scale and an offset), the FMU parameters it set, how it judged the
residuals (confidence, share, persistence, centring) and its calibration. As a diagram:

    signals (x scale + offset) -> model block -> residuals -> Deviation (T²) -> result, message
                                                     optional band on a signal -> in operation

and its cycle, window (the twin's horizon) and step become the algorithm's timing. The verdict
stays the same: the deviation block is the twin's judgement, ported whole.
"""

from __future__ import annotations

import re
from typing import Any

from plantcraft_sdk.blocks import VERSION

from linkcraft.blocks.models import layout_of, model_block_id

RESULT_NAME = "Model deviation"
COLUMNS = {"input": 40, "scale": 330, "model": 640, "judge": 960, "output": 1260}
ROW = 130


class _Diagram:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.rows: dict[str, int] = {}

    def node(self, node_id: str, block: str, column: str, **extra: Any) -> str:
        row = self.rows.get(column, 0)
        self.rows[column] = row + 1
        self.nodes.append(
            {
                "id": node_id,
                "block": block,
                "parameters": dict(extra.pop("parameters", None) or {}),
                "x": COLUMNS[column],
                "y": 40 + ROW * row,
                **{key: value for key, value in extra.items() if value},
            }
        )
        return node_id

    def wire(self, source: str, source_port: str, target: str, target_port: str) -> None:
        self.edges.append(
            {
                "source": source,
                "source_port": source_port,
                "target": target,
                "target_port": target_port,
            }
        )

    def done(self) -> dict[str, Any]:
        return {"version": VERSION, "nodes": self.nodes, "edges": self.edges}


def _signal_parameters(source: dict[str, Any], subject: str | None) -> dict[str, Any]:
    if source.get("signal_id"):
        return {"signal": source["signal_id"]}
    found = {"role": source.get("role") or ""}
    if source.get("asset_id") and source.get("asset_id") != subject:
        found["asset"] = source["asset_id"]
    return found


def _scaled(item: dict[str, Any]) -> bool:
    return float(item.get("scale", 1.0)) != 1.0 or float(item.get("offset", 0.0)) != 0.0


def twin_subject(twin: dict[str, Any]) -> str | None:
    """The asset a twin's algorithm runs on: the twin's own, else its first output's."""

    if twin.get("asset_id"):
        return str(twin["asset_id"])
    for item in twin.get("outputs") or []:
        asset = item.get("asset_id") or (item.get("source") or {}).get("asset_id")
        if asset:
            return str(asset)
    return None


def twin_diagram(
    twin: dict[str, Any], info: dict[str, Any], calibration: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The diagram of a twin (``TwinDraft`` fields) on its FMU (``info``: ``fmu.inspect_fmu``).

    ``KeyError`` names a twin variable the FMU does not have.
    """

    layout = layout_of(info)
    inputs = {item["name"]: port for port, item in layout.inputs}
    outputs = {item["name"]: port for port, item in layout.outputs}
    fields = {item["name"]: field for field, item in layout.parameters}
    subject = twin_subject(twin)
    detection = twin.get("detection") or {}
    d = _Diagram()

    def signal(node_id: str, item: dict[str, Any], label: str) -> tuple[str, str]:
        d.node(
            node_id,
            "input.signal",
            "input",
            parameters=_signal_parameters(item.get("source") or {}, subject),
            label=label,
        )
        if not _scaled(item):
            return node_id, "value"
        scaled = d.node(
            f"{node_id}_scaled",
            "transform.gain_offset",
            "scale",
            parameters={
                "gain": float(item.get("scale", 1.0)),
                "offset": float(item.get("offset", 0.0)),
            },
        )
        d.wire(node_id, "value", scaled, "x")
        return scaled, "value"

    parameters: dict[str, Any] = {
        "step_seconds": float(twin.get("step_seconds") or 5.0),
        "judged_seconds": float(twin.get("evaluate_seconds") or 600),
    }
    for name, value in (twin.get("parameters") or {}).items():
        parameters[fields[name]] = float(value)
    for item in twin.get("outputs") or []:
        port = outputs[item["variable"]]
        start = item.get("start_parameter")
        if start:
            if start not in fields:
                raise KeyError(start)
            parameters[f"{port}_start"] = start
    ports = [outputs[item["variable"]] for item in twin.get("outputs") or []]
    record = ports + [f"{port}_residual" for port in ports]
    model = d.node(
        "model",
        model_block_id(str(twin["model_id"])),
        "model",
        parameters=parameters,
        record=record,
    )
    for index, item in enumerate(twin.get("inputs") or []):
        source, port = signal(f"in_{index + 1}", item, str(item["variable"]))
        d.wire(source, port, model, inputs[item["variable"]])
    deviation = d.node(
        "deviation",
        "model.deviation",
        "judge",
        parameters={
            "confidence": float(detection.get("confidence", 0.99)),
            "share": float(detection.get("share", 0.2)),
            "persistence": int(detection.get("persistence", 3)),
            "centre": bool(detection.get("centre", False)),
            "calibration": calibration,
        },
        record=["t2"],
    )
    for index, item in enumerate(twin.get("outputs") or []):
        port = outputs[item["variable"]]
        source, source_port = signal(
            f"out_{index + 1}", item, str(item.get("label") or item["variable"])
        )
        d.wire(source, source_port, model, f"{port}_measured")
        d.wire(model, f"{port}_residual", deviation, "residuals")
    band = twin.get("active_when")
    if band:
        source, port = signal("active_signal", band, "")
        operating = d.node(
            "operating",
            "model.operating",
            "judge",
            parameters={"above": band.get("above"), "below": band.get("below")},
        )
        d.wire(source, port, operating, "x")
        d.wire(operating, "intervals", deviation, "active")
    result = d.node("result", "output.result", "output", parameters={"name": RESULT_NAME})
    message = d.node("message", "output.message", "output")
    d.wire(deviation, "result", result, "in")
    d.wire(deviation, "result", message, "in")
    return d.done()


def twin_timing(twin: dict[str, Any]) -> dict[str, float]:
    """The twin's cycle, horizon (the window) and step as an algorithm's timing."""

    return {
        "cycle_seconds": float(twin.get("cycle_seconds") or 60),
        "window_seconds": float(twin.get("horizon_seconds") or 1800),
        "step_seconds": float(twin.get("step_seconds") or 5.0),
    }


OUTPUT_LIKE = re.compile(r"(^u$|op|valve|mv|out)", re.IGNORECASE)


def _input_role(name: str) -> str:
    """A first guess of the role behind a model input: what a controller moves (u, OP, a valve)
    is the OP, anything else (a disturbance, a feed) the loop's secondary signal."""

    return "op" if OUTPUT_LIKE.search(name) else "secondary"


def model_starter(model: dict[str, Any]) -> dict[str, Any]:
    """A new algorithm on assets around a published model: a signal block on each of its inputs
    and outputs with a first guess of its role (outputs the PV; inputs the OP when they look like
    one, else the secondary signal) for the person to check, the model, Deviation (T²), a result
    and a message. What "Publish to Link" in Models opens."""

    info = model.get("info") or {}
    layout = layout_of(info)
    twin = {
        "model_id": model["model_id"],
        "inputs": [
            {"variable": item["name"], "source": {"role": _input_role(item["name"])}}
            for _port, item in layout.inputs
        ],
        "outputs": [
            {"variable": item["name"], "source": {"role": "pv"}} for _port, item in layout.outputs
        ],
    }
    return {
        "name": str(model.get("name") or model["model_id"])[:120],
        "description": str(model.get("description") or "")[:2000],
        "subject_kind": "asset",
        "diagram": twin_diagram(twin, info),
        "timing": twin_timing(twin),
    }


__all__ = ["RESULT_NAME", "model_starter", "twin_diagram", "twin_subject", "twin_timing"]


def repeated_twins(profiles: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The algorithms copied from Twin (``twin_<id>``) that repeat another algorithm of the site
    with the same name, which the demo's examples made too: each with the one it repeats. On an
    installation that ran both, the two ran on the same assets (owner, 2026-10-24: remove them,
    after a list and a confirmation)."""

    others: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        if not profile.get("system") and not str(profile["profile_id"]).startswith("twin_"):
            others.setdefault(str(profile.get("name") or "").strip().lower(), profile)
    found = []
    for profile in profiles:
        if profile.get("system") or not str(profile["profile_id"]).startswith("twin_"):
            continue
        same = others.get(str(profile.get("name") or "").strip().lower())
        if same is not None:
            found.append((profile, same))
    return found
