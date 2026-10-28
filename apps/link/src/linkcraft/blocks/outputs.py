"""Outputs: where an algorithm's results go.

An output block computes what it publishes and leaves it in ``ctx.extra["collected"]``; the
app publishes it after the run (``loops.suite``, ``signals.publish``):

- ``output.loop_health``: the loop's health, the verdict on the asset (``loop_health``) and its
  health and status series in the historian;
- ``output.result``: a named result on the asset, beside its health;
- ``output.message``: an event when its input turns bad, closed when it recovers;
- ``output.signal_quality``: a signal's verdict (``signal_quality``) from its checks.

Any number or verdict output of any block can also be recorded in the historian, per diagram
(``record`` on the node), without an output block.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from plantcraft_sdk.blocks import (
    Block,
    BlockDocs,
    BlockSpec,
    NoParameters,
    Result,
    inport,
)
from plantcraft_sdk.methods import MethodResult
from pydantic import BaseModel, Field

from linkcraft.blocks.health import loop_summary
from linkcraft.i18n import t


def output_key(name: str) -> str:
    """``Valve and PV`` -> ``valve_and_pv``: the result kind of a named output."""

    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:40]


def collected(ctx: Any) -> dict[str, Any]:
    return ctx.extra.setdefault("collected", {})


def _methods(items: Any) -> list[MethodResult]:
    found = []
    for item in items or []:
        method = item.detail.get("method") if isinstance(item, Result) else None
        if isinstance(method, MethodResult):
            found.append(method)
    return found


def health_of(
    frame: Any,
    scored: list[MethodResult],
    context: list[MethodResult],
    diagnostics: list[MethodResult],
    *,
    excluded: set[str] | None = None,
    data: Result | None = None,
) -> dict[str, Any]:
    """The loop summary: health from ``scored``, context and diagnostics beside it."""

    seen: set[str] = set()
    results = []
    for item in [*scored, *context, *diagnostics]:
        if item.method_id not in seen:
            seen.add(item.method_id)
            results.append(item)
    scored_ids = {item.method_id for item in scored}
    outside = {item.method_id for item in results if item.method_id not in scored_ids}
    summary = loop_summary(
        frame,
        results,
        outside | set(excluded or ()),
        {item.method_id for item in context},
        {item.method_id for item in diagnostics},
    )
    detail = data.detail if isinstance(data, Result) else {}
    reasons = [str(item) for item in detail.get("reasons") or []]
    if reasons and summary["status"] != "inactive":
        # An inactive loop (manual, output parked) explains bad data; that state is kept.
        summary.update(
            status="no_data",
            health=None,
            limiting=None,
            alerts=[],
            operating_state="unusable_data",
            operating_state_reason=" ".join(reasons),
        )
    return summary


def _loop_health(inputs: dict[str, Any], _parameters: Any, ctx: Any) -> dict[str, Any]:
    summary = health_of(
        ctx.extra.get("frame"),
        _methods(inputs.get("methods")),
        _methods(inputs.get("context")),
        _methods(inputs.get("diagnostics")),
        excluded=set(ctx.extra.get("health_excluded") or ()),
        data=inputs.get("data") if isinstance(inputs.get("data"), Result) else None,
    )
    collected(ctx)["health"] = {"node_id": ctx.node_id, "summary": summary}
    return {}


class OutputName(BaseModel):
    name: str = Field(
        default="",
        max_length=60,
        title="Name",
        description="Name people read in PlantCraft and Dashboards, such as Valve.",
    )


def _result(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    given = inputs.get("in")
    result = given if isinstance(given, Result) else Result.unknown(getattr(given, "reason", ""))
    name = parameters.name.strip()
    collected(ctx).setdefault("outputs", []).append(
        {
            "node_id": ctx.node_id,
            "kind": "result",
            "name": name or result.label or ctx.node_id,
            "key": output_key(name) if name else ctx.node_id,
            "status": result.status,
            "value": result.value,
            "message": result.message,
        }
    )
    return {}


class Message(BaseModel):
    when: Literal["bad", "warning_or_bad"] = Field(
        default="bad",
        title="Send when",
        description="Status of the input that sends the message.",
    )
    text: str = Field(
        default="",
        max_length=200,
        title="Text",
        description="What the message says (empty: the input's own sentence).",
    )


def _message(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    given = inputs.get("in")
    result = given if isinstance(given, Result) else Result.unknown(getattr(given, "reason", ""))
    triggered = result.status == "bad" or (
        parameters.when == "warning_or_bad" and result.status == "warning"
    )
    collected(ctx).setdefault("outputs", []).append(
        {
            "node_id": ctx.node_id,
            "kind": "message",
            "name": result.label or t("Message"),
            "key": ctx.node_id,
            "status": result.status,
            "value": result.value,
            "message": result.message,
            "triggered": triggered,
            "text": parameters.text.strip() or result.message,
        }
    )
    return {}


def combine_checks(signal_id: str, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """One signal's verdict from its checks: good, suspect, bad or unknown."""

    judged = [item for item in outcomes if item["status"] in ("ok", "warning", "bad")]
    if not judged:
        reasons = [item["message"] for item in outcomes if item.get("message")]
        return {
            "signal": signal_id,
            "status": "unknown",
            "quality": None,
            "apt": False,
            "limiting": None,
            "message": reasons[0] if reasons else t("No check could judge this signal."),
        }
    worst = max(judged, key=lambda item: item["score"])
    statuses = {item["status"] for item in judged}
    status = "bad" if "bad" in statuses else "suspect" if "warning" in statuses else "good"
    return {
        "signal": signal_id,
        "status": status,
        "quality": round(100.0 - worst["score"], 1),
        "apt": status != "bad",
        "limiting": worst["check"] if status != "good" else None,
        "message": worst["message"] if status != "good" else t("All checks passed."),
    }


def _signal_quality(inputs: dict[str, Any], _parameters: Any, ctx: Any) -> dict[str, Any]:
    outcomes = []
    for item in inputs.get("checks") or []:
        if isinstance(item, Result) and not item.detail.get("off"):
            outcome = item.detail.get("check")
            if isinstance(outcome, dict):
                outcomes.append(outcome)
    signal = ctx.extra.get("signal") or {}
    verdict = combine_checks(str(signal.get("id") or ctx.asset.get("id") or ""), outcomes)
    verdict["checks"] = outcomes
    collected(ctx)["signal"] = verdict
    return {}


DATA_TEXT = (
    "The loop data check's verdict: when the data is not usable the loop gets no health, "
    "and the reason is said."
)

BLOCKS = (
    Block(
        BlockSpec(
            "output.loop_health",
            "1.0",
            "output",
            "Loop health",
            BlockDocs(
                summary="The loop's health from 0 to 100, the method that limits it and the "
                "loop's state.",
                description=(
                    "Multiplies the scores of the verdicts wired to Score (each from 0 to 100) "
                    "into the loop's health, names the method that pulls it down the most and "
                    "the loop's state (active, manual, inactive, no data). Operator behaviour "
                    "wired to Context is shown beside the score, never in it; fault screenings "
                    "wired to Diagnostics are flagged when they warn. The health goes to the "
                    "loop's asset in PlantCraft as its loop_health result and to the "
                    "historian as its health and status series."
                ),
                reading=(
                    "Normal above 75, medium from 50 to 75, high from 25 to 50, critical at 25 "
                    "or less. No health in manual, with the output parked or when the data is "
                    "not usable: the reason replaces the score."
                ),
                assumptions=(
                    "The verdicts wired to Score measure the loop's performance, not the "
                    "operators' behaviour.",
                ),
                formula="health = 100 · Π (score_i / 100) over the scored verdicts that give "
                "a functional score; otherwise 100 − the worst method score.",
            ),
            inputs=(
                inport(
                    "methods",
                    "result",
                    "Score",
                    "The performance verdicts whose scores make the health; any number of wires.",
                    multiple=True,
                ),
                inport(
                    "context",
                    "result",
                    "Context",
                    "Operator behaviour (manual mode, interventions) shown beside the score, "
                    "never in it.",
                    required=False,
                    multiple=True,
                ),
                inport(
                    "diagnostics",
                    "result",
                    "Diagnostics",
                    "Fault screenings (stiction, oscillation, noise) flagged beside the score "
                    "when they warn.",
                    required=False,
                    multiple=True,
                ),
                inport("data", "result", "Data", DATA_TEXT, required=False),
            ),
            runs_on_missing=True,
            group="Assets",
        ),
        _loop_health,
    ),
    Block(
        BlockSpec(
            "output.result",
            "1.0",
            "output",
            "Result on the asset",
            BlockDocs(
                summary="Publishes a verdict on the asset in PlantCraft, under its own name.",
                description=(
                    "Writes the verdict wired to it as a result of the asset in PlantCraft "
                    "(kind out_<name>), beside its health, so every app, dashboard and the "
                    "assistant can read it. The result expires after two run periods, so a "
                    "stopped algorithm never leaves a green light behind."
                ),
                reading=(
                    "The asset shows the verdict's status (ok, warning, alarm) and its sentence "
                    "under the name given."
                ),
            ),
            inputs=(inport("in", "result", "Verdict", "The verdict to publish on the asset."),),
            parameters=OutputName,
            runs_on_missing=True,
            group="Assets",
        ),
        _result,
    ),
    Block(
        BlockSpec(
            "output.message",
            "1.0",
            "output",
            "Message",
            BlockDocs(
                summary="Sends a PlantCraft event when its input turns bad, and closes it "
                "when it recovers.",
                description=(
                    "Raises an alert event on the asset in PlantCraft (linkcraft.protocol."
                    "alert) the first run its input is bad (or warning, when chosen), and a "
                    "cleared event when it recovers. Nothing is sent while the status stays "
                    "the same, so a lasting problem gives one message."
                ),
                reading=(
                    "An open alert means the input is still bad; the cleared event closes it."
                ),
            ),
            inputs=(inport("in", "result", "Verdict", "The verdict that sends the message."),),
            parameters=Message,
            runs_on_missing=True,
            group="Assets",
        ),
        _message,
    ),
    Block(
        BlockSpec(
            "output.signal_quality",
            "1.0",
            "output",
            "Signal verdict",
            BlockDocs(
                summary="A signal's quality verdict from its checks: good, suspect, bad or "
                "unknown.",
                description=(
                    "Combines the data quality checks wired to it into the signal's verdict: "
                    "bad when any check is bad, suspect when any warns, good when every check "
                    "that could judge passed. Its quality is 100 minus the worst check's score "
                    "and its sentence the worst check's. The verdict goes to the signal in "
                    "PlantCraft (signal_quality) and decides whether loops may use the signal."
                ),
                reading=(
                    "Good: usable. Suspect: usable with care. Bad: loops using the signal are "
                    "not judged. Unknown: no check could judge (no data)."
                ),
            ),
            inputs=(
                inport(
                    "checks",
                    "result",
                    "Checks",
                    "The data quality checks of the signal; any number of wires.",
                    multiple=True,
                ),
            ),
            parameters=NoParameters,
            runs_on_missing=True,
            group="Signals",
        ),
        _signal_quality,
    ),
)
