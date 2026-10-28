"""HTTP routes the Notebooks app on a person's computer calls before it has a token.

"Connect this computer" (``POST /api/notebooks/pair``, signed in) opens a link with a one-time
code; the app trades it here for the kit's token (read-only, the person's own access,
``kits.KIT_TOKEN_DAYS``). The code is the proof: it lasts ``PAIR_SECONDS``, works once and only
its digest is kept. The installation's local certificate authority is public; the app checks it
against the SHA-256 the signed-in page put in the link before it trusts it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from processcraft.api.deps import Runtime
from processcraft.db import utc_text
from processcraft.i18n import t
from processcraft.notebooks import kits

router = APIRouter()


class RedeemPayload(BaseModel):
    code: str = Field(min_length=16, max_length=64)
    computer: str = Field(default="", max_length=80)


@router.post("/api/notebooks/pair/redeem")
def redeem(payload: RedeemPayload, rt: Runtime) -> dict[str, Any]:
    store = rt.workspace.notebooks
    settings = store.settings()
    if not (settings["enabled"] and settings["kit_enabled"]):
        raise HTTPException(status_code=404, detail=t("Not found."))
    username = store.redeem(payload.code)
    users = rt.workspace.users
    user = users.get_user(username) if username else None
    if not username or user is None or not users.is_active_person(username):
        raise HTTPException(
            status_code=404,
            detail=t("This code has expired or was used: click Connect this computer again."),
        )
    computer = " ".join(payload.computer.split())[:60]
    label = t(
        "Notebooks on {computer}, {date}", computer=computer or "a computer", date=utc_text()[:10]
    )
    try:
        record, token = rt.workspace.assistant_access.create(
            username, label=label, longest=kits.KIT_TOKEN_DAYS
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail=t("Revoke a token first: at most 10 can be active.")
        ) from exc
    detail = {"token_id": record["token_id"], "label": label, "expires_at": record["expires_at"]}
    rt.workspace.audit.record(
        username, "assistant_token.create", f"user:{username}", detail, app_id="processcraft"
    )
    return {
        "token": token,
        "expires_at": record["expires_at"],
        "username": username,
        "name": user.get("display_name") or username,
    }


@router.get("/api/notebooks/pair/ca")
def local_ca() -> Response:
    ca = kits.local_ca()
    if ca is None:
        raise HTTPException(status_code=404, detail=t("Not found."))
    return Response(ca, media_type="application/x-pem-file", headers={"Cache-Control": "no-store"})
