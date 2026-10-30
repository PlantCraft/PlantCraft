"""HTTP routes: app keys (administrators issue and revoke the keys apps use for service tokens).

The key is shown once, when created; only its hash is stored. Creating and
revoking a key is recorded in the audit log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plantcraft.api.deps import AdminUser, Runtime
from plantcraft.i18n import t

router = APIRouter(prefix="/api/app-keys")


class AppKeyPayload(BaseModel):
    app_id: str = Field(min_length=1, max_length=40)
    label: str = Field(default="", max_length=120)


@router.get("")
def list_keys(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Every key (active first) and the apps installed beside PlantCraft."""

    return {
        "keys": rt.workspace.app_keys.list(),
        "apps": [{"id": app.id, "name": app.name, "url": app.url} for app in rt.suite_apps()],
    }


@router.post("", status_code=201)
def create_key(payload: AppKeyPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A new key for the app; ``key`` is in this answer only (set it as ``PLANTCRAFT_APP_KEY``)."""

    try:
        record, key = rt.workspace.app_keys.create(payload.app_id, label=payload.label, actor=admin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(
        admin,
        "app_key.create",
        f"app:{record['app_id']}",
        {"key_id": record["key_id"], "label": record["label"]},
        app_id="processcraft",
    )
    return {**record, "key": key}


@router.delete("/{key_id}")
def revoke_key(key_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The key stops working at once, and so do the service tokens issued with it."""

    current = rt.workspace.app_keys.get(key_id)
    if current is None:
        raise HTTPException(status_code=404, detail=t("App key not found."))
    record = rt.workspace.app_keys.revoke(key_id, actor=admin) or current
    if current["active"]:
        rt.workspace.audit.record(
            admin,
            "app_key.revoke",
            f"app:{record['app_id']}",
            {"key_id": key_id},
            app_id="processcraft",
        )
    return record
