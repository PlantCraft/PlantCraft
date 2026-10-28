"""HTTP route: the read-only MCP server at ``/mcp`` (``processcraft/assistant_access/mcp.py``).

Off unless an administrator turned it on (404 then, as if it were not there). The caller sends
``Authorization: Bearer pcat_...``, a person's access token. Each tool call is answered by API v1
inside this process, with a token issued for that person at that moment, so a person who lost
access, a revoked token or an expired one stops at once. Every tool call is in the audit log.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from processcraft.api.deps import Runtime
from processcraft.api.identity import (
    READ_LEVELS,
    bearer_token,
    issue_user_token,
    user_claims,
    visible_apps,
)
from processcraft.assistant_access import mcp
from processcraft.i18n import t

router = APIRouter()

MAX_BODY = 256 * 1024


def _refused(status: int, detail: str) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return HTTPException(status_code=status, detail=detail, headers=headers)


def _same_origin(request: Request) -> bool:
    """A browser page of another site may not call the server (DNS rebinding)."""

    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    return urlsplit(origin).netloc == host


def _person(rt: Any, request: Request) -> tuple[dict[str, Any], str]:
    store = rt.workspace.assistant_access
    if not store.enabled():
        raise _refused(404, t("Not found."))
    if not _same_origin(request):
        raise _refused(403, t("Requests from another site are not accepted."))
    record = store.verify(bearer_token(request))
    if record is None:
        raise _refused(401, t("Send an active AI assistant access token (Bearer pcat_...)."))
    claims = user_claims(rt, record["username"])
    if claims is None or claims["level"] not in READ_LEVELS:
        raise _refused(403, t("This token's owner may no longer read the plant."))
    return record, record["username"]


@router.get("/mcp")
def mcp_stream(rt: Runtime, request: Request) -> Response:
    """No server-sent stream: every answer comes back on the POST."""

    _person(rt, request)
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp_post(rt: Runtime, request: Request) -> Response:
    record, username = _person(rt, request)
    body = await request.body()
    if len(body) > MAX_BODY:
        raise _refused(413, t("The request is too large."))
    try:
        message = json.loads(body or b"null")
    except ValueError:
        return JSONResponse(mcp.error(None, mcp.PARSE_ERROR, "Parse error"), status_code=400)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        # Batches went away in protocol 2025-06-18; anything else is not a request.
        return JSONResponse(
            mcp.error(None, mcp.INVALID_REQUEST, "Invalid request"), status_code=400
        )
    if "id" not in message:  # a notification (notifications/initialized...): nothing to answer
        return Response(status_code=202)
    answer = await _answer(rt, request, message, username, record["token_id"])
    return JSONResponse(answer)


async def _answer(
    rt: Any, request: Request, message: dict[str, Any], username: str, token_id: str
) -> dict[str, Any]:
    request_id = message["id"]
    method = message["method"]
    params = message.get("params") or {}
    if method == "initialize":
        from processcraft.api.app import platform_version

        return mcp.result(request_id, mcp.initialize(params, platform_version()))
    if method == "ping":
        return mcp.result(request_id, {})
    apps = visible_apps(rt, username)
    # The apps' own tools (``[[contributes.assistant.tools]]``) of the apps this person may open.
    added = {tool.name: tool.tool() for tool in rt.app_tools.for_apps(apps)}
    if method == "tools/list":
        listed = [*mcp.TOOLS, *added.values()]
        return mcp.result(request_id, {"tools": [tool.describe() for tool in listed]})
    if method != "tools/call":
        return mcp.error(request_id, mcp.METHOD_NOT_FOUND, f"Method not found: {method}")
    if not isinstance(params, dict):
        return mcp.error(request_id, mcp.INVALID_PARAMS, "params must be an object")
    name = str(params.get("name") or "")
    tool = mcp.BY_NAME.get(name) or added.get(name)
    if tool is None:
        return mcp.error(request_id, mcp.INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
    try:
        arguments = mcp.check_arguments(tool, params.get("arguments"))
    except mcp.InvalidArguments as exc:
        return mcp.error(request_id, mcp.INVALID_PARAMS, str(exc))
    issued = issue_user_token(rt, username)
    if issued is None:
        return mcp.error(request_id, mcp.INVALID_PARAMS, "This person may no longer sign in.")
    rt.workspace.audit.record(
        username,
        "mcp.tool",
        f"tool:{tool.name}",
        {"token_id": token_id, "arguments": arguments},
        app_id="processcraft",
    )
    # The results, events and runs of apps the person may not open stay out (as in Desk's chat).
    answer = await mcp.call_in_process(request.app, issued["token"], tool, arguments, apps)
    return mcp.result(request_id, answer)
