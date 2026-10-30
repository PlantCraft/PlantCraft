"""API v1: an app writes with a language model through PlantCraft (owner, 2026-10-25).

An app declares each use in ``[[contributes.llm]]`` of its ``app.toml``; PlantCraft keeps it
with the rest of what the app adds (``plantcraft.apps.contributions``), and Settings › Language
models lists it as ``<app id>:<id>``, where an administrator gives it the default, another
model or none. ``POST /api/v1/llm/{use}`` answers with the model of that use: PlantCraft keeps
the key, counts the calls per plant day (``PLANTCRAFT_LLM_APP_DAILY``, 500 by default) and
records each one in the audit log. A model only reads what the app sends: it never acts on the
plant or the suite.

What leaves the plant is the administrator's call (security audit, 2026-10-26): the app's token
needs ``write.llm`` in its ``[permissions]`` (shown before the install), and a use of an app
outside the suite's own bundle starts off whatever it declares, until an administrator gives it
a model; only the suite's apps (``PLANTCRAFT_APPS``) may start on the default.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from plantcraft.api.deps import Runtime
from plantcraft.api.identity import V1Caller
from plantcraft.auth.suite import suite_apps
from plantcraft.config import plant_timezone
from plantcraft.i18n import t
from plantcraft.specialists.profiles import models_allowed_for
from plantcraft_sdk.llm import messages_body, split_use

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)

# The longest text an app may send in one call (characters, every message together).
MAX_CHARS = 200_000


def first_choice(app: str, declared: str) -> str:
    """What a use writes with before an administrator chooses: what it declares for an app of
    the suite's bundle, off for any other app."""

    return declared if app in {item.id for item in suite_apps()} else "off"


def _daily() -> int:
    try:
        value = int(os.environ.get("PLANTCRAFT_LLM_APP_DAILY", "") or 500)
    except ValueError:
        return 500
    return max(1, min(100_000, value))


@router.post("/llm/{use}")
def llm(use: str, caller: V1Caller, rt: Runtime, body: Any = Body(None)) -> dict[str, Any]:
    """One answer from the model of one of the app's uses (``<id>`` or ``<app id>:<id>``):
    ``{use, model, text}``."""

    app = caller.app_id
    if not app:
        raise HTTPException(status_code=403, detail=t("Only an app's own token sends this."))
    try:
        name = split_use(app, use)
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail=t("A service token writes only for its own app.")
        ) from exc
    declared = next(
        (
            item
            for item in ((rt.contributions.get(app) or {}).get("contributes") or {}).get("llm", [])
            if item["id"] == name
        ),
        None,
    )
    if declared is None:
        raise HTTPException(
            status_code=404,
            detail=t("{app} declares no use {use} in [[contributes.llm]].", app=app, use=name),
        )
    body = body if isinstance(body, dict) else {}
    try:
        request = messages_body(body.get("messages") or [], system=str(body.get("system") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    sent = len(request["system"]) + sum(len(item["content"]) for item in request["messages"])
    if sent > MAX_CHARS:
        raise HTTPException(
            status_code=413, detail=t("At most {count} characters a call.", count=MAX_CHARS)
        )
    qualified = f"{app}:{name}"
    found = rt.specialists.use_model(
        qualified, first_choice(app, declared.get("default", "default"))
    )
    if found is None or not models_allowed_for(None):
        raise HTTPException(
            status_code=409,
            detail=t(
                "This use has no language model now. An administrator chooses one in Settings, "
                "Language models."
            ),
        )
    day = datetime.now(plant_timezone()).date().isoformat()
    if not rt.specialists.count_app_call(app, day, _daily()):
        raise HTTPException(
            status_code=429, detail=t("{app} wrote with a model enough times today.", app=app)
        )
    model = rt.specialist_chat.model_factory(
        found["key"],
        provider=found["kind"],
        model=found["name"],
        endpoint=found["endpoint"],
        reasoning=found["reasoning"],
    )
    try:
        text = model.answer(request["system"], request["messages"])
    except Exception as exc:  # the model's server: down, wrong key, refused
        logger.warning("Model of %s did not answer: %s", qualified, exc)
        raise HTTPException(
            status_code=502, detail=t("The model did not answer: {error}", error=str(exc)[:300])
        ) from exc
    rt.workspace.audit.record(
        caller.username,
        "language_model.used",
        f"settings:language-model:{qualified}",
        {"provider": found["label"], "model": found["name"], "sent": sent, "answer": len(text)},
    )
    return {"use": qualified, "model": f"{found['label']} · {found['name']}", "text": text}
