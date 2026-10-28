"""View's uses of a language model (``[[contributes.llm]]`` in ``app.toml``), asked through
PlantCraft (``POST /api/v1/llm/{use}``): PlantCraft picks the model, keeps the key and counts
the calls; View never sees either. Every use ships off until an administrator gives it a model
in Setup › Language models."""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.client import PlantCraftError

from dashcraft.i18n import t

DIAGRAM_DRAFT = "diagram-draft"


class NoModel(Exception):
    """No model for this use now (off, or none set up), or View has no app key."""


def ask(client: Any, use: str, text: str, *, system: str = "") -> str:
    """The model's answer to ``text`` for one of View's uses (raises NoModel when there is no
    model, PlantCraftError when PlantCraft could not answer)."""

    if client is None:
        raise NoModel(t("This installation gave View no app key, so it cannot ask a model."))
    try:
        answer = client.llm(use, text, system=system)
    except PlantCraftError as exc:
        if exc.status_code in (404, 409):
            raise NoModel(str(exc.detail)) from exc
        raise
    return str((answer or {}).get("text") or "")
