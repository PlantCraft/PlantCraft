"""Logic: combine verdicts, and turn a number into a verdict."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from plantcraft_sdk.blocks import (
    SEVERITY,
    Block,
    BlockDocs,
    BlockSpec,
    NoData,
    NoParameters,
    Result,
    inport,
    outport,
)
from pydantic import BaseModel, Field

from linkcraft.i18n import t

RESULTS = inport(
    "in",
    "result",
    "Verdicts",
    "The verdicts to combine; any number of wires.",
    multiple=True,
)
OUT = outport("result", "result", "Verdict", "The combined verdict: status, score and sentence.")


def _judged(items: list[Any]) -> list[Result]:
    return [item for item in items if isinstance(item, Result) and item.status != "unknown"]


def _worst(inputs: dict[str, Any], _parameters: Any, ctx: Any) -> dict[str, Any]:
    judged = _judged(inputs.get("in") or [])
    if not judged:
        return {"result": Result.unknown(t("None of the inputs could judge."))}
    worst = max(
        judged,
        key=lambda item: (
            SEVERITY[item.status],
            -(item.value if item.value is not None else 101.0),
        ),
    )
    values = [item.value for item in judged if item.value is not None]
    message = worst.message
    if worst.label and worst.status != "ok":
        message = f"{worst.label}: {message}"
    return {"result": Result(worst.status, min(values) if values else None, message, worst.label)}


class Average(BaseModel):
    warning_below: float = Field(
        default=80.0,
        ge=0,
        le=100,
        title="Warning below",
        description="Average score under which the verdict is a warning.",
    )
    bad_below: float = Field(
        default=50.0,
        ge=0,
        le=100,
        title="Bad below",
        description="Average score under which the verdict is bad.",
    )


def _status(score: float, warning_below: float, bad_below: float) -> str:
    return "bad" if score < bad_below else "warning" if score < warning_below else "ok"


def _average(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    values = [item.value for item in _judged(inputs.get("in") or []) if item.value is not None]
    if not values:
        return {"result": Result.unknown(t("None of the inputs has a score."))}
    mean = float(np.mean(values))
    status = _status(mean, parameters.warning_below, parameters.bad_below)
    message = t("Average of {count} inputs: {value}/100.", count=len(values), value=round(mean))
    return {"result": Result(status, mean, message)}


class Rule(BaseModel):
    when: Literal["bad", "warning_or_bad", "unknown"] = Field(
        default="bad",
        title="When the test is",
        description="Status of the test input that triggers the rule.",
    )
    then: Literal["unknown", "bad", "warning", "ok"] = Field(
        default="unknown",
        title="Then the verdict is",
        description="Status the verdict takes when the rule triggers.",
    )
    message: str = Field(
        default="",
        max_length=200,
        title="Sentence",
        description="Sentence of the verdict when the rule triggers (empty: the test's own).",
    )


def _rule(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    test = inputs.get("test")
    value = inputs.get("value")
    test = test if isinstance(test, Result) else Result.unknown(getattr(test, "reason", ""))
    status = test.status
    triggered = status == parameters.when or (
        parameters.when == "warning_or_bad" and status in {"warning", "bad"}
    )
    if triggered:
        then = parameters.then
        message = parameters.message.strip() or test.message
        score = {"ok": 100.0, "bad": 0.0}.get(then, test.value if then == "warning" else None)
        return {"result": Result(then, score, message, test.label)}
    if not isinstance(value, Result):
        return {"result": Result("ok", 100.0, t("The rule did not trigger."))}
    return {"result": Result(value.status, value.value, value.message, value.label)}


class Limits(BaseModel):
    better: Literal["lower", "higher"] = Field(
        default="lower",
        title="Better when",
        description="Whether a lower or a higher number is the good direction.",
    )
    warning: float = Field(
        default=50.0,
        title="Warning limit",
        description="Value past which (in the bad direction) the verdict is a warning.",
    )
    bad: float = Field(
        default=80.0,
        title="Bad limit",
        description="Value past which (in the bad direction) the verdict is bad.",
    )
    sentence: str = Field(
        default="",
        max_length=200,
        title="Sentence",
        description="What the verdict says; {value} is replaced by the number.",
    )


def _limits(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    number = inputs.get("x")
    if isinstance(number, NoData) or number is None:
        return {"result": Result.unknown(t("No number to judge."))}
    value = float(number)
    if parameters.better == "lower":
        status = (
            "bad" if value >= parameters.bad else "warning" if value >= parameters.warning else "ok"
        )
        span = parameters.bad if parameters.bad else 1.0
        score = 100.0 * (1.0 - min(1.0, max(0.0, value / span)))
    else:
        status = (
            "bad" if value <= parameters.bad else "warning" if value <= parameters.warning else "ok"
        )
        span = parameters.warning if parameters.warning else 1.0
        score = 100.0 * min(1.0, max(0.0, value / span))
    text = parameters.sentence.strip()
    message = (
        text.replace("{value}", f"{value:g}")
        if text
        else t("Value {value}: {status}.", value=f"{value:g}", status=t(status))
    )
    return {"result": Result(status, score, message)}


BLOCKS = (
    Block(
        BlockSpec(
            "logic.worst",
            "1.0",
            "logic",
            "Worst of",
            BlockDocs(
                summary="The most severe of several verdicts, with the lowest score among them.",
                description=(
                    "Takes the verdicts wired to it and keeps the most severe status (bad, then "
                    "warning, then ok) and the lowest score. Its sentence is the worst input's, "
                    "named after the block it came from. Verdicts that could not judge are left "
                    "out."
                ),
                reading=(
                    "Bad when any input is bad, warning when any warns, ok when all pass; "
                    "unknown when no input could judge."
                ),
                formula="status = worst(status₁ … statusₙ)    score = min(score₁ … scoreₙ)",
            ),
            inputs=(RESULTS,),
            outputs=(OUT,),
            runs_on_missing=True,
            group="Combine",
        ),
        _worst,
    ),
    Block(
        BlockSpec(
            "logic.average",
            "1.0",
            "logic",
            "Average",
            BlockDocs(
                summary="The mean score of several verdicts, with a status from two limits.",
                description=(
                    "Averages the scores of the verdicts wired to it and gives the status from "
                    "the average: a warning under the warning limit and bad under the bad "
                    "limit. Unlike the worst-of block, one poor input does not decide alone."
                ),
                reading=(
                    "The score is the plain average from 0 to 100; ok, warning and bad follow "
                    "from the two limits."
                ),
                formula=(
                    "score = (score₁ + … + scoreₙ) / n\n"
                    "status = bad if score < bad limit, warning if score < warning limit, else ok"
                ),
            ),
            inputs=(RESULTS,),
            outputs=(OUT,),
            parameters=Average,
            runs_on_missing=True,
            group="Combine",
        ),
        _average,
    ),
    Block(
        BlockSpec(
            "logic.rule",
            "1.0",
            "logic",
            "Rule (if … then)",
            BlockDocs(
                summary="When a test verdict has the chosen status, the output takes the rule's "
                "status.",
                description=(
                    "Reads a test verdict and, when its status is the one chosen (bad, warning "
                    "or bad, unknown), gives the rule's status and sentence; otherwise it passes "
                    "the value input on unchanged. Use it to say 'when the PV's signal is bad, "
                    "the valve verdict is unknown'."
                ),
                reading=(
                    "When the rule triggers, the verdict is the rule's; otherwise it is the "
                    "value input's (or ok when nothing is wired to value)."
                ),
                formula="result = rule's status if status(test) = when, else value",
            ),
            inputs=(
                inport(
                    "test", "result", "Test", "The verdict that decides whether the rule triggers."
                ),
                inport(
                    "value",
                    "result",
                    "Value",
                    "The verdict passed on when the rule does not trigger.",
                    required=False,
                ),
            ),
            outputs=(OUT,),
            parameters=Rule,
            runs_on_missing=True,
            group="Combine",
        ),
        _rule,
    ),
    Block(
        BlockSpec(
            "logic.limits",
            "1.0",
            "logic",
            "Limit check",
            BlockDocs(
                summary="Turns a number into a verdict with a warning and a bad limit.",
                description=(
                    "Compares a number, such as a stiction index or a valve travel, with two "
                    "limits in the direction that is bad (higher or lower), and gives a status, "
                    "a score from 0 to 100 and a sentence. It makes any metric a verdict that "
                    "can be combined, published or sent as a message."
                ),
                reading=(
                    "Ok before the warning limit, warning between the two limits, bad past the "
                    "bad limit; unknown when the number is missing."
                ),
                formula=(
                    "lower is better: bad if x ≥ bad, warning if x ≥ warning, else ok;\n"
                    "  score = 100 · (1 − x / bad), clipped to 0 … 100\n"
                    "higher is better: bad if x ≤ bad, warning if x ≤ warning, else ok;\n"
                    "  score = 100 · x / warning, clipped to 0 … 100"
                ),
            ),
            inputs=(inport("x", "number", "Number", "The number to judge, in its own unit."),),
            outputs=(OUT,),
            parameters=Limits,
            runs_on_missing=True,
            group="Judge",
        ),
        _limits,
    ),
)

__all__ = ["BLOCKS", "NoParameters"]
