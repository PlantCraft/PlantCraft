"""The setup guide's routes (``plantcraft/api/setup_guide.py``, docs/setup-guide.md), administrators
only.

- ``GET /api/setup-guide``: every step with its state and facts, and the step that comes now.
- ``POST /api/setup-guide/steps/{step}``: mark a step done or skipped, or take the mark back.
- ``POST /api/setup-guide/hide``: hide the robot for this administrator, or bring it back.
- ``POST /api/setup-guide/basics`` and ``/connection``: what a step's card applies when the person
  clicks it. The robot only proposes; these routes write, as the person who clicked, through the
  same code as the step's own page (Settings › Installation, Sources), so the checks, the audit
  and the errors are that page's.
- ``POST /api/setup-guide/connection/{source}/test``: try a saved source now, so the guide sees the
  connection as soon as it answers.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plantcraft.api import setup_guide
from plantcraft.api.deps import AdminUser, Runtime
from plantcraft.api.routers import data, installation
from plantcraft.i18n import t
from plantcraft.platform.datalayer.histcraft import ENDPOINT_FIELD

router = APIRouter(prefix="/api/setup-guide")


class MarkPayload(BaseModel):
    state: Literal["done", "skipped"] | None = None


class HidePayload(BaseModel):
    hidden: bool = True


class BasicsPayload(BaseModel):
    time_zone: str = Field(min_length=1, max_length=64)
    language: str | None = Field(default=None, max_length=10)


class ConnectionPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["opcua", "pi_web_api", "csv"] = "opcua"
    endpoint: str = Field(min_length=1, max_length=500)
    username: str = Field(default="", max_length=200)
    namespace_uri: str = Field(default="", max_length=500)


@router.get("")
def guide(admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    return setup_guide.status(rt, admin)


@router.post("/steps/{step}")
def mark_step(step: str, payload: MarkPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    if step not in setup_guide.step_ids():
        raise HTTPException(status_code=404, detail=t("The setup guide has no such step."))
    setup_guide.mark(rt, step, payload.state, actor=admin)
    return setup_guide.status(rt, admin)


@router.post("/hide")
def hide(payload: HidePayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    setup_guide.hide(rt, admin, payload.hidden)
    return setup_guide.status(rt, admin)


@router.post("/basics")
def apply_basics(payload: BasicsPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The time zone (Settings › Installation) and the person's own language (Preferences)."""

    zone = payload.time_zone.strip()
    if (
        zone != rt.workspace.installation.settings()["time_zone"]
        or not (rt.workspace.installation.settings()["chosen"])
    ):
        installation.save_installation(installation.InstallationPayload(time_zone=zone), admin, rt)
    language = (payload.language or "").strip() or None
    if language is not None:
        if language not in {"en", "pt-BR", "es"}:
            raise HTTPException(
                status_code=422, detail=t("Unknown language: {language}.", language=language)
            )
        mine = installation.preferences(rt, admin)
        installation.save_my_preferences(
            installation.PreferencesPayload(time_zone=mine["time_zone"], language=language),
            admin,
            rt,
        )
    setup_guide.mark(rt, "basics", "done", actor=admin)
    return {"id": "basics", "time_zone": zone, "language": language}


@router.post("/connection", status_code=201)
def apply_connection(payload: ConnectionPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A plant source, as Sources › Add saves one, then a first try of its connection."""

    settings: dict[str, Any] = {ENDPOINT_FIELD[payload.kind]: payload.endpoint.strip()}
    if payload.username.strip():
        settings["username"] = payload.username.strip()
    if payload.namespace_uri.strip():
        settings["namespace_uri"] = payload.namespace_uri.strip()
    made = data.create_source(
        data.SourcePayload(name=payload.name.strip(), type=payload.kind, settings=settings),
        admin,
        rt,
    )
    source_id = str(made.get("source_id") or made.get("id") or "")
    tested = _test(rt, admin, source_id) if source_id else None
    return {"id": source_id, "source": made, "test": tested}


@router.post("/connection/{source_id}/test")
def test_connection(source_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    return {"test": _test(rt, admin, source_id), "guide": setup_guide.status(rt, admin)}


def _test(rt: Any, admin: str, source_id: str) -> dict[str, Any]:
    try:
        answer = data.source_status(source_id, admin, rt, refresh=True)
    except HTTPException as exc:
        answer = {"ok": False, "message": str(exc.detail)}
    except Exception as exc:  # a source that cannot be reached says why, the guide keeps going
        answer = {"ok": False, "message": str(exc) or type(exc).__name__}
    result = {
        "ok": bool(answer.get("ok")),
        "message": str(answer.get("message") or "")[:300],
    }
    stored = rt.workspace.preferences.get(setup_guide.INSTALLATION, setup_guide.KEY)
    tested = dict((stored or {}).get("tested") or {}) if isinstance(stored, dict) else {}
    tested[source_id] = result
    setup_guide.remember(rt, tested=dict(list(tested.items())[-20:]))
    return result
