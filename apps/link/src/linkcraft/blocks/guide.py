"""What an assistant needs to write a new block in Link's format: the block file, the rules its
code follows, the port types, a complete example and the blocks that already exist.

``new_block_guide`` is the text behind "New block > With the assistant": copied as a prompt for
any LLM, or written to PlantCraft for the suite's assistant before the person asks it. The
answer is a block file people import (``blocks.files``).
"""

from __future__ import annotations

import json
from typing import Any

from plantcraft_sdk.blocks import TYPE_DESCRIPTIONS

from linkcraft.blocks.catalog import catalog_items, libraries
from linkcraft.blocks.files import FORMAT, OPEN_LIBRARIES
from linkcraft.blocks.sandbox import ALLOWED_MODULES

EXAMPLE_CODE = '''import numpy as np
import pandas as pd


def run(inputs, params, ctx):
    """Fouling of a heat exchanger read from its UA: the slope of UA over the window."""
    duty = inputs["duty"]
    lmtd = inputs["lmtd"]
    ua = (duty / lmtd.where(lmtd.abs() > params.min_lmtd)).dropna()
    if len(ua) < params.min_points:
        return {"ua": ua, "trend": NoData("Too few points with a usable temperature difference.")}
    hours = (ua.index - ua.index[0]).total_seconds() / 3600.0
    slope = float(np.polyfit(hours, ua.to_numpy(dtype=float), 1)[0])
    change = 100.0 * slope * 24.0 / max(abs(float(ua.mean())), 1e-9)
    if change <= -params.bad_percent_per_day:
        status = "bad"
    elif change <= -params.bad_percent_per_day / 2:
        status = "warning"
    else:
        status = "ok"
    score = max(0.0, min(100.0, 100.0 + 100.0 * change / (2 * params.bad_percent_per_day)))
    message = f"UA changes {change:+.2f} % per day."
    return {"ua": ua, "trend": Result(status, score, message)}
'''

EXAMPLE: dict[str, Any] = {
    "format": FORMAT,
    "block_id": "equipment.ua_fouling_trend",
    "name": "UA fouling trend",
    "library": "equipment",
    "group": "Heat exchanger",
    "tags": ["heat exchanger", "fouling"],
    "origin": "assistant",
    "docs": {
        "summary": "Whether a heat exchanger is fouling: how fast its UA falls over the window.",
        "description": (
            "Computes UA = Q / LMTD at each step where the temperature difference is usable, "
            "fits a straight line to it and reports the change in percent of the mean per day."
        ),
        "reading": (
            "ok: UA steady or rising. warning: falling faster than half the limit. bad: falling "
            "faster than the limit (bad_percent_per_day)."
        ),
        "assumptions": ["Duty and LMTD are on the same time grid, in consistent units."],
        "limitations": ["A change of flow regime also moves UA; read it with the flows."],
        "formula": "UA(t) = Q(t) / LMTD(t); trend = slope(UA) × 24 / mean(UA) × 100 %/day",
        "references": [
            "Incropera, F. P., DeWitt, D. P. (2007). Fundamentals of Heat and Mass Transfer, "
            "6th ed. Wiley. Chapter 11."
        ],
    },
    "inputs": [
        {
            "port": "duty",
            "type": "series",
            "label": "Duty",
            "unit": "kW",
            "description": "Heat duty Q.",
        },
        {
            "port": "lmtd",
            "type": "series",
            "label": "LMTD",
            "unit": "K",
            "description": "Log-mean temperature difference.",
        },
    ],
    "outputs": [
        {
            "port": "ua",
            "type": "series",
            "label": "UA",
            "unit": "kW/K",
            "description": "Overall heat transfer coefficient times area.",
            "record": True,
        },
        {
            "port": "trend",
            "type": "result",
            "label": "Fouling",
            "description": "ok, warning or bad from the UA trend, with the change per day.",
        },
    ],
    "parameters": [
        {
            "name": "min_lmtd",
            "type": "number",
            "title": "Smallest LMTD",
            "default": 2.0,
            "minimum": 0.1,
            "unit": "K",
            "description": "Steps with a smaller temperature difference are left out.",
        },
        {
            "name": "min_points",
            "type": "integer",
            "title": "Fewest points",
            "default": 20,
            "minimum": 3,
            "description": "Fewer usable steps than this and the block does not judge.",
        },
        {
            "name": "bad_percent_per_day",
            "type": "number",
            "title": "Bad decline",
            "default": 2.0,
            "minimum": 0.01,
            "unit": "%/day",
            "description": "A UA falling faster than this is bad; half of it is a warning.",
        },
    ],
    "code": EXAMPLE_CODE,
}

RULES = (
    "Answer with ONE JSON object in the format {format} and nothing else (no prose around it).",
    "code defines run(inputs, params, ctx) and returns a dict with one value per output port.",
    "inputs[port] is a pandas Series on a DatetimeIndex (series, state, intervals: True inside), "
    "a float (number) or a Result; None when an optional input is not wired; a list for a "
    "multiple input.",
    "params.<name> reads a parameter; ctx.start and ctx.end are the window (pandas Timestamps), "
    "ctx.asset the asset, ctx.state a dict the block keeps between runs.",
    "Return Result(status, score, message) for a verdict: status ok, warning, bad or unknown, "
    "score 0 to 100 where 100 is best. Return NoData(reason) when the block cannot judge, "
    "never a guess. Result and NoData need no import.",
    "Import only: {modules}. No files, no network, no eval or exec, no attribute that starts "
    "with _ (the code is checked and runs in a restricted process).",
    "Every port and parameter has a description a process engineer understands; give units. "
    "Parameters are number, integer, boolean, text or choice, each with a default.",
    "library is one of {libraries}; block_id is <library>.<name in snake_case>.",
    "Bad data never crashes: NaN, gaps, constant signals and short windows give NoData or an "
    "unknown Result with the reason.",
    "Cite the method's source in docs.references (author, title, year) when it comes from a "
    "paper or a book.",
)


def rules() -> list[str]:
    return [
        rule.format(
            format=FORMAT,
            modules=", ".join(sorted(ALLOWED_MODULES)),
            libraries=", ".join(OPEN_LIBRARIES),
        )
        for rule in RULES
    ]


def existing_blocks() -> list[str]:
    """The catalog in one line per block, so the answer reuses ids and does not duplicate."""

    names = {item["library"]: item["name"] for item in libraries()}
    return [
        f"- `{item['block_id']}` ({names.get(item['library'], item['library'])}): {item['summary']}"
        for item in catalog_items()
        if item["library"] not in {"input", "output"}
    ]


def port_types() -> list[str]:
    return [f"- `{key}`: {text}" for key, text in TYPE_DESCRIPTIONS.items()]


def new_block_guide(request: str = "") -> str:
    """The whole text, Markdown: the request first, then the format, rules, example, catalog."""

    lines = ["# Write a new block for PlantCraft Analytics", ""]
    if request.strip():
        lines += ["## What the block must do", "", request.strip(), ""]
    lines += [
        "## The answer",
        "",
        *[f"{number}. {rule}" for number, rule in enumerate(rules(), start=1)],
        "",
        "## Port types",
        "",
        *port_types(),
        "",
        "## A complete example",
        "",
        "```json",
        json.dumps(EXAMPLE, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Blocks that already exist (reuse their ideas, do not repeat them)",
        "",
        *existing_blocks(),
        "",
    ]
    return "\n".join(lines)


__all__ = ["EXAMPLE", "new_block_guide", "rules"]
