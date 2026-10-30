"""HTTP routes: API v1's tools the apps add to the assistant (docs/assistant.md, "Tools the apps add").

``GET /api/v1/tools`` lists the tools of the apps the person may open; ``POST
/api/v1/apps/<app>/tools/<id>`` checks the arguments against what the app declared in
``[[contributes.assistant.tools]]`` and forwards the call to the app as the person
(``plantcraft.api.app_proxy.post_tool``). Desk's assistant and the MCP server call the tools
through this route, so the app's access checks and audit apply the same everywhere.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Request, Response
from starlette.concurrency import run_in_threadpool

from plantcraft.api import app_proxy as proxy
from plantcraft.api.deps import Runtime
from plantcraft.api.identity import Caller, V1Reader
from plantcraft.assistant_access import mcp
from plantcraft.i18n import t

router = APIRouter(prefix="/api/v1")
AppId = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
ToolId = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{1,40}$")]
# Arguments are a question and a few fields, never data.
MAX_BODY = 16 * 1024


def _person(caller: Caller) -> str:
    if caller.app_id:
        raise HTTPException(status_code=403, detail=t("An app calls another app itself."))
    return caller.username


def _installed(rt: Any) -> set[str]:
    return {app.id for app in rt.suite_apps()}


@router.get("/tools")
def tools(caller: V1Reader, rt: Runtime) -> dict[str, Any]:
    """The tools the apps this person may open add to the assistant."""

    _person(caller)
    installed = _installed(rt)
    return {
        "tools": [
            {
                "name": tool.name,
                "app": tool.app,
                "id": tool.id,
                "title": tool.title,
                "description": tool.tool().description,
                "reads": tool.reads,
                "input_schema": tool.tool().describe()["inputSchema"],
            }
            for tool in rt.app_tools.for_apps(set(caller.apps))
            if tool.app in installed
        ]
    }


@router.post("/apps/{app}/tools/{tool_id}")
async def call_tool(
    app: AppId, tool_id: ToolId, caller: V1Reader, rt: Runtime, request: Request
) -> Response:
    """Call one app's tool with the person's identity; the app's answer comes back as it is."""

    username = _person(caller)
    found = rt.app_tools.find(app, tool_id)
    if found is None or app not in caller.apps or app not in _installed(rt):
        raise HTTPException(
            status_code=404, detail=t("This app offers no such tool, or you may not open it.")
        )
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(status_code=413, detail=t("The tool's arguments are too large."))
    try:
        arguments = mcp.check_arguments(found.tool(), json.loads(body or b"{}"))
    except (ValueError, mcp.InvalidArguments) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        answer = await run_in_threadpool(proxy.post_tool, rt, app, tool_id, username, arguments)
    except proxy.AppUnreachable as exc:
        raise HTTPException(
            status_code=503, detail=t("{app} does not answer. Try again in a moment.", app=app)
        ) from exc
    if answer.status >= 500:
        raise HTTPException(status_code=502, detail=t("{app} could not answer.", app=app))
    return Response(content=answer.body, status_code=answer.status, media_type=answer.content_type)
