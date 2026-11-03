"""Conditions: where a signal is past a limit, and conditions combined with AND, OR and NOT.

A condition is the ``intervals`` port type: a true/false series on the algorithm's grid, which
Select by condition, Only in operation, the statistics and Deviation (T²) read.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, inport, outport
from pydantic import BaseModel, Field

from linkcraft.blocks.base import condition, numeric
from linkcraft.i18n import t

LIBRARY = "logic"
OUT = outport("intervals", "intervals", "Condition", "True where the condition holds.")


class Compare(BaseModel):
    operator: Literal[">", ">=", "<", "<="] = Field(
        default=">",
        title="Condition",
        description="How the signal must stand against the limit for the condition to hold.",
    )
    limit: float = Field(
        default=0.0, title="Limit", description="The value compared with, in the signal's unit."
    )
    deadband: float = Field(
        default=0.0,
        ge=0,
        title="Deadband",
        description="How far back past the limit the signal must go to end the condition; 0: none.",
    )


def _compare(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    x = numeric(inputs["x"])
    above = parameters.operator in (">", ">=")
    limit, band = parameters.limit, parameters.deadband
    ops = {">": x.gt, ">=": x.ge, "<": x.lt, "<=": x.le}
    on = ops[parameters.operator](limit)
    if band <= 0:
        found = on
    else:
        # Hysteresis: on past the limit, off only once back past the limit minus the deadband.
        off = x.lt(limit - band) if above else x.gt(limit + band)
        state, flags = False, []
        for is_on, is_off in zip(on.to_numpy(), off.to_numpy(), strict=True):
            state = True if is_on else False if is_off else state
            flags.append(state)
        found = pd.Series(flags, index=x.index)
    found = found & x.notna()
    found.name = f"x {parameters.operator} {limit:g}"
    return {"intervals": found.astype(bool)}


class Combine(BaseModel):
    mode: Literal["and", "or"] = Field(
        default="and",
        title="Combine with",
        description="AND: true where every condition holds; OR: where at least one holds.",
    )
    invert: bool = Field(
        default=False,
        title="NOT (invert)",
        description="Turn the combined condition around: true where it does not hold.",
    )


def _combine(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    given = [item for item in inputs.get("in") or [] if isinstance(item, pd.Series)]
    if not given:
        raise ValueError(t("Wire at least one condition."))
    index = given[0].index
    for item in given[1:]:
        index = index.union(item.index)
    flags = [condition(item, index) for item in given]
    found = flags[0]
    for item in flags[1:]:
        found = (found & item) if parameters.mode == "and" else (found | item)
    if parameters.invert:
        found = ~found
    return {"intervals": found.astype(bool)}


BLOCKS = (
    Block(
        BlockSpec(
            "logic.compare",
            "1.0",
            LIBRARY,
            "Compare with a limit",
            BlockDocs(
                summary="Where a signal is above or below a limit: a condition on the window.",
                description=(
                    "Marks the samples where the signal is above (or below) the limit: a feed "
                    "flow above its minimum says the unit runs, a temperature above its alarm "
                    "says it is too hot. A deadband keeps a noisy signal near the limit from "
                    "switching the condition on and off at every sample."
                ),
                reading="True where the signal is past the limit; empty samples count as false.",
                formula="c(t) = x(t) > limit (or ≥, <, ≤), with hysteresis of the deadband",
            ),
            inputs=(inport("x", "series", "Signal", "The signal compared with the limit."),),
            outputs=(OUT,),
            parameters=Compare,
            group="Conditions",
        ),
        _compare,
    ),
    Block(
        BlockSpec(
            "logic.combine",
            "1.0",
            LIBRARY,
            "AND / OR / NOT",
            BlockDocs(
                summary="Combines conditions with AND or OR, and turns them around with NOT.",
                description=(
                    "Joins two or more conditions sample by sample: AND holds where all of them "
                    "hold (the unit runs and the analyser is valid), OR where any holds (either "
                    "pump runs). NOT inverts the result, so one block also gives 'outside the "
                    "condition'."
                ),
                reading="True where the combined condition holds.",
                formula="c(t) = c1(t) ∧ c2(t) ∧ … (or ∨), then ¬ if NOT is on",
            ),
            inputs=(
                inport(
                    "in",
                    "intervals",
                    "Conditions",
                    "The conditions to combine; one or more wires.",
                    multiple=True,
                ),
            ),
            outputs=(OUT,),
            parameters=Combine,
            group="Conditions",
        ),
        _combine,
    ),
)

__all__ = ["BLOCKS"]
