"""HTTP routes: the Operations page (administrators): backups, restores, the drill, updates;
and Health's read-only view for everyone (``/status``).

PlantCraft writes requests and reads answers; the installer and its driver do the work
(``plantcraft.apps.operations_desk``, docs/operations.md). A restore replaces every
database, so it asks for the administrator's password and the backup's name typed again.
Every request is in the audit log.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from plantcraft.api.deps import AdminUser, AdminView, CurrentUser, Runtime
from plantcraft.api.identity import issue_user_token
from plantcraft.apps.manager import AppError
from plantcraft.i18n import t
from plantcraft.platform.datalayer import DataLayerError

router = APIRouter(prefix="/api/operations")


class OperationRequest(BaseModel):
    name: str | None = Field(default=None, max_length=60)


class RestoreRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    typed_name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class Schedule(BaseModel):
    enabled: bool | None = None
    daily_at: str | None = Field(default=None, max_length=5)
    timezone: str | None = Field(default=None, max_length=60)
    drill: bool | None = None
    drill_weekday: int | None = None
    drill_at: str | None = Field(default=None, max_length=5)


def _http(error: AppError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.message)


def _audit(rt: Any, admin: str, action: str, detail: Any = None) -> None:
    rt.workspace.audit.record(admin, action, "suite:operations", detail, app_id="processcraft")


def _password_ok(rt: Any, username: str, password: str) -> bool:
    if not rt.auth.enabled:
        return True  # local use without sign-in: nobody to ask
    if hmac.compare_digest(username, rt.auth.username) and hmac.compare_digest(
        password, rt.auth.password
    ):
        return True
    return rt.workspace.users.verify_password(username, password)


@router.get("")
def overview(_admin: AdminView, rt: Runtime) -> dict[str, Any]:
    """Backups and their checks, the operation running, the history, the last update."""

    return {**rt.operations.overview(), "installer": rt.apps.installer()}


@router.get("/health")
def health(_admin: AdminView, rt: Runtime) -> dict[str, Any]:
    """The suite watch: what it looked at last, open and recent incidents, Docker's view."""

    return rt.watch.overview()


# What everyone may see of Health: whether each part of the suite runs. The
# disk, the backups, the certificates and the services' resources stay with the administrators.
STATUS_CHECKS = ("service:", "queue:")
SERVICE_FIELDS = ("service", "name", "state", "health", "started_at")


@router.get("/status")
def status(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Health for everyone: each service's state and the open incidents about services."""

    seen = rt.watch.overview()
    services = (seen.get("metrics") or {}).get("services") or []
    return {
        "at": seen.get("at"),
        "watching": bool(seen.get("watching")),
        "held": bool(seen.get("held")),
        "services": [{key: item.get(key) for key in SERVICE_FIELDS} for item in services],
        "open": [
            {key: item.get(key) for key in ("incident_id", "subject", "detail", "opened_at")}
            for item in seen.get("open") or []
            if str(item.get("check_key") or "").startswith(STATUS_CHECKS)
        ],
    }


@router.post("/certificates/{certificate_id}/renew")
def renew_certificate(certificate_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A new client certificate for the Historian's OPC UA connections (the servers must trust
    it again: the answer carries it to download)."""

    issued = issue_user_token(rt, admin)
    if issued is None:
        raise HTTPException(403, t("Only admins change the installation's settings."))
    try:
        renewed = rt.datalayer.renew_certificate(certificate_id, issued["token"])
    except DataLayerError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    _audit(rt, admin, "certificate.renewed", {"id": certificate_id})
    rt.watch.forget_certificates()
    return renewed


@router.put("/schedule")
def set_schedule(payload: Schedule, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    try:
        value = rt.operations.set_schedule(changes)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, "operations.schedule", value)
    return value


@router.post("/restore")
def restore(payload: RestoreRequest, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    if payload.typed_name.strip() != payload.name:
        raise HTTPException(422, t("Type the backup's name exactly to confirm."))
    if not _password_ok(rt, admin, payload.password):
        _audit(rt, admin, "operations.restore.refused", {"name": payload.name})
        raise HTTPException(403, t("Wrong password."))
    try:
        queued = rt.operations.request("restore", admin, name=payload.name)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, "operations.restore", {"name": payload.name, **queued})
    return queued


@router.post("/diagnostics")
def diagnostics(admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Ask the installer for a diagnostic bundle (docs/operations.md, section 4)."""

    queued = rt.operations.request_diagnostics(admin)
    _audit(rt, admin, "operations.diagnostics", queued)
    return queued


@router.get("/diagnostics/{request_id}")
def download_diagnostics(request_id: str, admin: AdminUser, rt: Runtime) -> FileResponse:
    try:
        path = rt.operations.diagnostics_file(request_id)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, "operations.diagnostics.download", {"request_id": request_id})
    name = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"processcraft-diagnostics-{name}.zip",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{action}")
def start(action: str, payload: OperationRequest, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Back up now, check a backup, run the restore drill or apply retention."""

    if action == "restore":
        raise HTTPException(405, t("A restore needs a password confirmation."))
    try:
        queued = rt.operations.request(action, admin, name=payload.name)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, f"operations.{action}", queued)
    return queued


@router.get("/requests/{request_id}")
def outcome(request_id: str, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        return rt.operations.outcome(request_id)
    except AppError as exc:
        raise _http(exc) from exc
