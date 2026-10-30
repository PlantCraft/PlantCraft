"""HTTP routes: the Apps page (administrators install, update, roll back and remove apps).

Three ways in (docs/app-standard.md, section 8): a signed package uploaded from
a file, the same package from the online catalog (off until an administrator
turns it on, and only when ``PLANTCRAFT_APP_CATALOG_URL`` is set), or an app
already running elsewhere, registered by its address and given an app key. PlantCraft only
verifies and records; the installer service applies (docs/app-package.md).
Every change is in the audit log.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from plantcraft.api.deps import AdminUser, AdminView, Runtime
from plantcraft.apps.contributions import summary as contributions_summary
from plantcraft.apps.manager import AppError
from plantcraft.auth.suite import suite_apps
from plantcraft.i18n import t

router = APIRouter(prefix="/api/apps")


class ExternalApp(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=1, max_length=300)
    version: str | None = Field(default=None, max_length=40)
    # What its token may do in API v1 (plantcraft_sdk.scopes ids); by default it reads the
    # plant and writes to the audit log.
    permissions: list[str] | None = Field(default=None, max_length=40)


class CatalogSwitch(BaseModel):
    enabled: bool


class CatalogChoice(BaseModel):
    version: str | None = Field(default=None, max_length=40)


def _http(error: AppError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.message)


def _configured() -> list[tuple[str, str]]:
    return [(app.id, app.url) for app in suite_apps()]


def _audit(rt: Any, admin: str, action: str, app_id: str, detail: Any = None) -> None:
    rt.workspace.audit.record(admin, action, f"app:{app_id}", detail, app_id="processcraft")


def _issuer(rt: Any, admin: str):
    def issue(app_id: str) -> tuple[str, str]:
        record, key = rt.workspace.app_keys.create(app_id, label="Installed app", actor=admin)
        _audit(
            rt, admin, "app_key.create", app_id, {"key_id": record["key_id"], "via": "app install"}
        )
        return record["key_id"], key

    return issue


@router.get("")
def overview(_admin: AdminView, rt: Runtime) -> dict[str, Any]:
    """Settings of app management and every app: configured by hand, installed or external."""

    rt.sync_apps(force=True)
    configured = [
        {
            "id": app.id,
            "name": app.name,
            "version": app.version,
            "url": app.url,
            "origin": "configured",
            "status": "configured",
            "message": "",
            "summary": "",
            "publisher": {},
            "permissions": [],
            "previous_version": None,
            "has_sbom": False,
            "needs_key": False,
            "health": None,
        }
        for app in suite_apps()
    ]
    ids = {item["id"] for item in configured}
    installed = [rt.apps.public(row) for row in rt.apps.store.list() if row["app_id"] not in ids]
    # What each app told PlantCraft it adds when it last started (docs/app-standard.md, 4b).
    registry = {item["app"]: item for item in rt.contributions.listing()}
    apps = [
        {
            **item,
            "adds": contributions_summary(registry[item["id"]]) if item["id"] in registry else None,
            "adds_unknown": registry[item["id"]]["unknown"] if item["id"] in registry else [],
        }
        for item in configured + installed
    ]
    return {**rt.apps.settings_view(), "apps": apps}


@router.post("/packages", status_code=201)
async def upload_package(request: Request, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The package file as the request body; answers what it holds, for the admin to confirm."""

    manager = rt.apps
    try:
        upload_id, path = manager.new_upload_path()
    except AppError as exc:
        raise _http(exc) from exc
    limit = manager.settings.max_bytes + 64 * 1024
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(
            status_code=413, detail=t("The package is larger than this server accepts.")
        )
    size = 0
    try:
        with path.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=413, detail=t("The package is larger than this server accepts.")
                    )
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    try:
        preview = await run_in_threadpool(manager.stage, upload_id, path, admin, _configured())
    except AppError as exc:
        _audit(
            rt,
            admin,
            "app.package.rejected",
            "unknown",
            {"reason": exc.message[:500], "size": size},
        )
        raise _http(exc) from exc
    app = preview["app"]
    _audit(
        rt,
        admin,
        "app.package.verified",
        app["id"],
        {"version": app["version"], "sha256": app["sha256"], "publisher": app["publisher"]},
    )
    return preview


@router.get("/packages/{upload_id}")
def package_preview(upload_id: str, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        return rt.apps.preview(upload_id)
    except AppError as exc:
        raise _http(exc) from exc


@router.get("/packages/{upload_id}/sbom")
def package_sbom(upload_id: str, _admin: AdminUser, rt: Runtime) -> Response:
    try:
        document = rt.apps.upload_sbom(upload_id)
    except AppError as exc:
        raise _http(exc) from exc
    return Response(document, media_type="application/spdx+json")


@router.delete("/packages/{upload_id}")
def discard_package(upload_id: str, _admin: AdminUser, rt: Runtime) -> dict[str, bool]:
    try:
        rt.apps.discard(upload_id)
    except AppError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.post("/packages/{upload_id}/install", status_code=202)
def install_package(upload_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The administrator confirmed: the installer receives the verified package."""

    try:
        preview = rt.apps.preview(upload_id)
        app = rt.apps.confirm(upload_id, admin, _configured(), _issuer(rt, admin))
    except AppError as exc:
        raise _http(exc) from exc
    summary = preview["app"]
    _audit(
        rt,
        admin,
        "app.install.request",
        app["id"],
        {
            "version": summary["version"],
            "origin": preview["origin"],
            "sha256": summary["sha256"],
            "publisher": summary["publisher"],
            "permissions": [item["id"] for item in summary["permissions"]],
            "request_id": app["request_id"],
        },
    )
    return app


@router.get("/catalog")
def catalog(_admin: AdminView, rt: Runtime) -> dict[str, Any]:
    """The online catalog's apps; ``enabled: false`` (and how to switch it on) when it is off."""

    if not rt.apps.settings.catalog_url:
        return {
            "enabled": False,
            "configured": False,
            "apps": [],
            "how": t(
                "Set PLANTCRAFT_APP_CATALOG_URL to the address of a signed catalog and restart "
                "PlantCraft, then turn the catalog on here. Leave it unset in isolated plants: "
                "install from a file instead."
            ),
        }
    if not rt.apps.catalog_switch():
        return {
            "enabled": False,
            "configured": True,
            "apps": [],
            "how": t(
                "An administrator turns the catalog on here. Packages from it are checked against "
                "the trusted publishers like a file."
            ),
        }
    try:
        return {"enabled": True, "configured": True, "apps": rt.apps.catalog()}
    except AppError as exc:
        raise _http(exc) from exc


@router.put("/catalog")
def switch_catalog(payload: CatalogSwitch, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Turns the online catalog on or off (off by default; the signature is always checked)."""

    try:
        catalog = rt.apps.set_catalog(payload.enabled, admin)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, "app.catalog.switch", "catalog", {"enabled": payload.enabled})
    return catalog


@router.post("/catalog/{app_id}/download", status_code=201)
def catalog_download(
    app_id: str, admin: AdminUser, rt: Runtime, payload: CatalogChoice | None = None
) -> dict[str, Any]:
    """Downloads and verifies a catalog package; then it waits for confirmation like an upload."""

    try:
        preview = rt.apps.download(
            app_id, payload.version if payload else None, admin, _configured()
        )
    except AppError as exc:
        raise _http(exc) from exc
    app = preview["app"]
    _audit(
        rt,
        admin,
        "app.catalog.download",
        app["id"],
        {"version": app["version"], "sha256": app["sha256"], "publisher": app["publisher"]},
    )
    return preview


@router.post("/external", status_code=201)
def register_external(payload: ExternalApp, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """An app already running elsewhere: listed in the launcher; its code is not verified here."""

    try:
        app = rt.apps.register_external(
            payload.id,
            payload.name,
            payload.url,
            payload.version,
            admin,
            _configured(),
            _issuer(rt, admin),
            permissions=payload.permissions,
        )
    except AppError as exc:
        raise _http(exc) from exc
    _audit(
        rt,
        admin,
        "app.external.register",
        app["id"],
        {
            "name": app["name"],
            "url": app["url"],
            "version": app["version"],
            "health": app["health"],
        },
    )
    return {
        **app,
        "warning": t(
            "PlantCraft did not verify this app's code: it only links to it. Copy its app key "
            "now into the app's PLANTCRAFT_APP_KEY_FILE; it is not shown again."
        ),
    }


@router.post("/{app_id}/check")
def check_app(app_id: str, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        return rt.apps.check(app_id)
    except AppError as exc:
        raise _http(exc) from exc


@router.post("/{app_id}/uninstall", status_code=202)
def uninstall_app(app_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        row = rt.apps.store.get(app_id)
        app = rt.apps.uninstall(app_id, admin)
    except AppError as exc:
        raise _http(exc) from exc
    if app["origin"] == "external" and row and row.get("key_id"):
        rt.workspace.app_keys.revoke(row["key_id"], actor=admin)
    action = "app.external.remove" if app["origin"] == "external" else "app.uninstall.request"
    _audit(
        rt, admin, action, app_id, {"version": app["version"], "request_id": app.get("request_id")}
    )
    return app


@router.post("/{app_id}/rollback", status_code=202)
def rollback_app(app_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        app = rt.apps.rollback(app_id, admin)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(
        rt,
        admin,
        "app.rollback.request",
        app_id,
        {"from": app["version"], "to": app["previous_version"], "request_id": app["request_id"]},
    )
    return app


@router.post("/{app_id}/key", status_code=202)
def give_key(app_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A new app key for an installed app (one installed from the command line has none yet)."""

    try:
        app = rt.apps.set_key(app_id, admin, _issuer(rt, admin))
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, "app.key.request", app_id, {"request_id": app["request_id"]})
    return app


@router.get("/{app_id}/sbom")
def app_sbom(app_id: str, _admin: AdminUser, rt: Runtime, version: str | None = None) -> Response:
    row = rt.apps.store.get(app_id)
    wanted = version or (row or {}).get("version")
    document = rt.apps.sbom(app_id, str(wanted)) if row and wanted else None
    if document is None:
        raise HTTPException(status_code=404, detail=t("No SBOM for this app."))
    try:
        json.loads(document)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=t("No SBOM for this app.")) from exc
    return Response(document, media_type="application/spdx+json")
