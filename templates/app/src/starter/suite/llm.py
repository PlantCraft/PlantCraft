"""StarterCraft's one use of a language model, ``summary`` (``[[contributes.llm]]``, off until an
administrator gives it a model in Setup › Language models). PlantCraft holds the keys and picks
the model; the app sends only the note's text."""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.client import PlantCraftError

USE = "summary"
SYSTEM = "Summarise the operator's note on a plant asset in one short sentence."


class NoModel(Exception):
    """No model for this use now (off, or none set up), or no app key."""


def summary(client: Any, text: str) -> str:
    if client is None:
        raise NoModel("This installation gave StarterCraft no app key.")
    try:
        return str(client.llm(USE, text, system=SYSTEM)["text"])
    except PlantCraftError as exc:
        if exc.status_code in (404, 409):
            raise NoModel(str(exc)) from exc
        raise
