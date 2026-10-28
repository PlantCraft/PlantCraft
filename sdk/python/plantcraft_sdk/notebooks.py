"""Notebooks of the suite: one way to write them, for PlantCraft and for every app.

Every notebook starts the same way: install ``plantcraft-notebook`` (served by PlantCraft itself,
offline, in the browser; the PlantCraft Notebooks app has it already on a computer) and import it
as ``pc``. An app writes its examples with these helpers, so they read and start like
PlantCraft's own, and serves them with ``plantcraft_sdk.server.objects.notebooks_router``::

    from plantcraft_sdk.notebooks import Example, cell

    EXAMPLES = [
        Example(
            "run-a-block",
            "Run a block",
            "Read a loop's signals and run one of Link's blocks on them, on your computer.",
            lambda: [cell("code", 'link = pc.app("link")'), cell("code", "link.blocks()")],
        ),
    ]

PlantCraft shows them in ``Examples/<app>`` (``Examples/Analytics``), in the browser and on the
person's computer.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

PACKAGE = "plantcraft-notebook"
MODULE = "plantcraft_notebook"
FORMAT = "plantcraft-notebooks/1"
KERNEL = {"name": "python", "display_name": "Python (Pyodide)", "language": "python"}


def cell(kind: str, source: str) -> dict[str, Any]:
    """A ``markdown`` or ``code`` cell; the source's first and last blank lines go."""

    if kind not in ("markdown", "code"):
        raise ValueError("a cell is markdown or code")
    found: dict[str, Any] = {"id": secrets.token_hex(4), "cell_type": kind, "metadata": {}}
    found["source"] = source.strip("\n")
    if kind == "code":
        found.update(execution_count=None, outputs=[])
    return found


def notebook(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """An ``.ipynb`` document (nbformat 4) of ``cells``."""

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": KERNEL,
            "language_info": {"name": "python"},
            "plantcraft": {"created_at": datetime.now(UTC).isoformat(timespec="seconds")},
        },
        "cells": cells,
    }


SETUP = f"""
# In PlantCraft this installs the package from the server (no internet needed).
# On your computer the PlantCraft Notebooks app has it already.
%pip install -q {PACKAGE}
import matplotlib.pyplot as plt
import pandas as pd
import {MODULE} as pc
pc.me()
"""


def setup(intro: str) -> list[dict[str, Any]]:
    """The first two cells of every notebook: ``intro`` (markdown) and the setup cell."""

    return [cell("markdown", intro), cell("code", SETUP)]


def literal(value: Any) -> str:
    """``value`` as Python source (a string, a number, a list of strings)."""

    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class Example:
    """A ready notebook: ``id`` (a slug, its file name), ``title``, a one-line ``summary`` and the
    function that writes its cells after the setup cells."""

    id: str
    title: str
    summary: str
    cells: Callable[[], list[dict[str, Any]]]

    def notebook(self) -> dict[str, Any]:
        intro = f"""
# Example: {self.title}

{self.summary.strip()}

Run each cell with **Shift + Enter**, from the top. Times are the plant's local time.
Examples are read-only: **File › Save As** keeps your own copy in My notebooks.
"""
        return notebook(setup(intro) + self.cells())

    def item(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title, "summary": self.summary}


def example_problems(examples: list[Example]) -> list[str]:
    """What is wrong with a set of examples: repeated ids or titles, a cell that is not one."""

    problems: list[str] = []
    for field in ("id", "title"):
        values = [getattr(item, field) for item in examples]
        twice = sorted({value for value in values if values.count(value) > 1})
        if twice:
            problems.append(f"example {field} used more than once: {', '.join(twice)}")
    for item in examples:
        try:
            cells = item.notebook()["cells"]
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            problems.append(f"example {item.id!r} cannot be written: {exc}")
            continue
        if not any(
            MODULE in "".join(c.get("source") or "") for c in cells if c["cell_type"] == "code"
        ):
            problems.append(f"example {item.id!r} does not import {MODULE}")
    return problems


__all__ = [
    "Example",
    "FORMAT",
    "KERNEL",
    "MODULE",
    "PACKAGE",
    "SETUP",
    "cell",
    "example_problems",
    "literal",
    "notebook",
    "setup",
]
