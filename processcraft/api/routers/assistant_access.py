"""HTTP routes: AI assistant access (the MCP server's switch and the people's access tokens).

Administrators turn the read-only MCP server on and off and see or revoke every token; each
person creates and revokes their own (``processcraft/assistant_access``). A token is in the
answer that creates it only. Every change is in the audit log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from processcraft.api.deps import AdminUser, CurrentUser, Runtime, open_to, user_access
from processcraft.assistant_access import MAX_DAYS
from processcraft.i18n import t

router = APIRouter(prefix="/api/assistant-access")


class SettingsPayload(BaseModel):
    enabled: bool
    max_days: int = Field(default=30, ge=1, le=MAX_DAYS)


class TokenPayload(BaseModel):
    label: str = Field(default="", max_length=120)
    days: int | None = Field(default=None, ge=1, le=MAX_DAYS)


def _endpoint(request: Request) -> str:
    """The address an assistant connects to: this server's /mcp, as the browser reached it."""

    forwarded = request.headers.get("x-forwarded-proto")
    scheme = forwarded or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    return f"{scheme}://{host}/mcp"


def _audit(rt: Any, actor: str, action: str, subject: str, detail: dict[str, Any]) -> None:
    rt.workspace.audit.record(actor, action, subject, detail, app_id="processcraft")


@router.get("")
def settings(_admin: AdminUser, rt: Runtime, request: Request) -> dict[str, Any]:
    """The switch, the longest a token may last, and every person's tokens."""

    store = rt.workspace.assistant_access
    return {**store.settings(), "endpoint": _endpoint(request), "tokens": store.list()}


@router.put("")
def save_settings(payload: SettingsPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    store = rt.workspace.assistant_access
    if payload.enabled and not store.settings()["allowed"]:
        raise HTTPException(
            status_code=409,
            detail=t("This installation turned the MCP server off (PLANTCRAFT_MCP=off)."),
        )
    saved = store.save_settings(enabled=payload.enabled, max_days=payload.max_days, actor=admin)
    _audit(
        rt,
        admin,
        "assistant_access.settings",
        "setting:mcp",
        {"enabled": saved["enabled"], "max_days": saved["max_days"]},
    )
    return saved


@router.get("/mine")
@open_to("dashboards")
def my_tokens(user: CurrentUser, rt: Runtime, request: Request) -> dict[str, Any]:
    """What a person sees on their profile: whether it is on and their own tokens."""

    store = rt.workspace.assistant_access
    access = user_access(rt, user)
    current = store.settings()
    return {
        "enabled": current["enabled"],
        "max_days": current["max_days"],
        "can_create": bool(
            (current["enabled"] or rt.workspace.notebooks.enabled())
            and access
            and access.at_least("viewer")
        ),
        "endpoint": _endpoint(request),
        "tokens": store.list(user),
    }


@router.post("/mine", status_code=201)
@open_to("viewer")
def create_token(payload: TokenPayload, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A new token for the signed-in person; ``token`` is in this answer only."""

    store = rt.workspace.assistant_access
    # The same tokens read API v1 from a notebook on the person's computer (docs/en/notebooks.md).
    if not (store.enabled() or rt.workspace.notebooks.enabled()):
        raise HTTPException(
            status_code=409, detail=t("An administrator has to turn AI assistant access on first.")
        )
    try:
        record, token = store.create(user, label=payload.label, days=payload.days)
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail=t("Revoke a token first: at most 10 can be active.")
        ) from exc
    _audit(
        rt,
        user,
        "assistant_token.create",
        f"user:{user}",
        {
            "token_id": record["token_id"],
            "label": record["label"],
            "expires_at": record["expires_at"],
        },
    )
    return {**record, "token": token}


@router.delete("/mine/{token_id}")
@open_to("dashboards")
def revoke_my_token(token_id: str, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    store = rt.workspace.assistant_access
    current = store.get(token_id)
    if current is None or current["username"] != user:
        raise HTTPException(status_code=404, detail=t("Token not found."))
    record = store.revoke(token_id, actor=user) or current
    _audit(rt, user, "assistant_token.revoke", f"user:{user}", {"token_id": token_id})
    return record


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """An administrator ends anyone's token at once."""

    store = rt.workspace.assistant_access
    current = store.get(token_id)
    if current is None:
        raise HTTPException(status_code=404, detail=t("Token not found."))
    record = store.revoke(token_id, actor=admin) or current
    _audit(
        rt,
        admin,
        "assistant_token.revoke",
        f"user:{current['username']}",
        {"token_id": token_id},
    )
    return record
