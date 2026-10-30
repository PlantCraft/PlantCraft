"""HTTP routes: API v1's objects of the apps, for notebooks (docs/api-v1.md, "Apps' objects").

One format for every app (owner, 2026-10-26): an app declares its kinds in
``[[contributes.objects]]`` and serves them at ``<prefix>api/objects/<kind>``
(``plantcraft_sdk.server.objects``); PlantCraft lists what each app offers and forwards the
reads with the person's identity (``plantcraft.api.app_proxy``), so a notebook reads Link's blocks
or Models' models with the same access token and the same per-person limits as the plant's data.
What runs on the person's computer comes from ``/notebooks/runtime``: nothing a notebook runs
runs on the server. The one write is ``POST .../objects/<kind>/run`` for a kind the app runs
itself (``run = "app"``: a simulation in its queue), which the app refuses unless its
administrator switched notebook runs on (owner, 2026-10-26, D4).
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field

from plantcraft.api import app_proxy as proxy
from plantcraft.api.deps import Runtime
from plantcraft.api.identity import Caller, V1Reader
from plantcraft.i18n import t

router = APIRouter(prefix="/api/v1")
AppId = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
Kind = Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{0,40}$")]
FORWARDED_QUERY = {"version"}
# What a run request may carry: a stop time, a few parameters, never data.
MAX_RUN_BYTES = 16 * 1024


class RunBody(BaseModel):
    id: str = Field(min_length=1, max_length=400)
    options: dict[str, Any] = Field(default_factory=dict, max_length=100)


def _person(caller: Caller) -> str:
    if caller.app_id:
        raise HTTPException(status_code=403, detail=t("An app reads another app's objects itself."))
    return caller.username


def _offered(rt: Any, caller: Caller) -> list[dict[str, Any]]:
    """What each installed app the person may open offers notebooks, in the suite's order."""

    apps = {app.id: app for app in rt.suite_apps()}
    found = []
    for row in rt.contributions.listing(list(apps)):
        if row["app"] not in caller.apps:
            continue
        contributes = row.get("contributes") or {}
        kinds = contributes.get("objects") or []
        notebooks = contributes.get("notebooks") or {}
        if not kinds and not notebooks.get("examples"):
            continue
        app = apps[row["app"]]
        found.append(
            {
                "app": app.id,
                "name": app.name,
                "prefix": app.url,
                "version": row.get("version") or "",
                "kinds": [
                    {
                        "kind": item["kind"],
                        "title": item.get("title") or item["kind"],
                        "description": item.get("description") or "",
                        "run": item.get("run") or "none",
                    }
                    for item in kinds
                ],
                "examples": bool(notebooks.get("examples")),
                "runtime": bool(notebooks.get("entry")),
            }
        )
    return found


def _kinds(rt: Any, caller: Caller, app: str) -> dict[str, Any]:
    found = next((item for item in _offered(rt, caller) if item["app"] == app), None)
    if found is None:
        raise HTTPException(
            status_code=404, detail=t("This app offers nothing here, or you may not open it.")
        )
    return found


def _forward(rt: Any, caller: Caller, app: str, path: str, request: Request) -> Response:
    params = {key: value for key, value in request.query_params.items() if key in FORWARDED_QUERY}
    headers = {}
    if request.headers.get("if-none-match"):
        headers["If-None-Match"] = request.headers["if-none-match"]
    try:
        answer = proxy.get(rt, app, path, _person(caller), params=params, headers=headers)
    except proxy.AppUnreachable as exc:
        raise HTTPException(
            status_code=503, detail=t("{app} does not answer. Try again in a moment.", app=app)
        ) from exc
    if answer.status >= 500:
        raise HTTPException(status_code=502, detail=t("{app} could not answer.", app=app))
    return Response(
        content=answer.body,
        status_code=answer.status,
        media_type=answer.content_type,
        headers=answer.headers,
    )


@router.get("/objects")
def offered(caller: V1Reader, rt: Runtime) -> dict[str, Any]:
    """The apps' kinds of object a notebook may read (and run), by app."""

    _person(caller)
    return {"apps": _offered(rt, caller)}


@router.get("/apps/{app}/objects/{kind}")
def objects(app: AppId, kind: Kind, caller: V1Reader, rt: Runtime, request: Request) -> Response:
    """The objects of one kind, as the app lists them for this person (``plantcraft-objects/1``)."""

    if kind not in {item["kind"] for item in _kinds(rt, caller, app)["kinds"]}:
        raise HTTPException(status_code=404, detail=t("No objects of this kind."))
    return _forward(rt, caller, app, f"api/objects/{kind}", request)


@router.get("/apps/{app}/objects/{kind}/{object_id:path}")
def one_object(
    app: AppId, kind: Kind, object_id: str, caller: V1Reader, rt: Runtime, request: Request
) -> Response:
    """One object, whole: what a notebook needs to read it or run it."""

    if kind not in {item["kind"] for item in _kinds(rt, caller, app)["kinds"]}:
        raise HTTPException(status_code=404, detail=t("No objects of this kind."))
    if not object_id or len(object_id) > 200 or ".." in object_id.split("/"):
        raise HTTPException(status_code=404, detail=t("Not found."))
    return _forward(rt, caller, app, f"api/objects/{kind}/{object_id}", request)


@router.get("/apps/{app}/notebooks/runtime")
def runtime_file(app: AppId, caller: V1Reader, rt: Runtime, request: Request) -> Response:
    """The app's runtime (a zip of its Python packages) that runs its objects on the person's
    computer or in their browser."""

    if not _kinds(rt, caller, app)["runtime"]:
        raise HTTPException(status_code=404, detail=t("This app runs nothing on your computer."))
    return _forward(rt, caller, app, "api/notebooks/runtime", request)


@router.post("/apps/{app}/objects/{kind}/run", status_code=201)
def run_object(app: AppId, kind: Kind, body: RunBody, caller: V1Reader, rt: Runtime) -> Response:
    """Ask the app to run one object (``run = "app"``): the app starts it in its own queue, with
    the person's access, when its administrator allows notebook runs; read back what it
    answers in ``started`` (``{"kind": "run", "id": ...}``)."""

    found = _kinds(rt, caller, app)
    spec = next((item for item in found["kinds"] if item["kind"] == kind), None)
    if spec is None or spec["run"] != "app":
        raise HTTPException(
            status_code=404,
            detail=t("Objects of this kind do not run in {app}.", app=found["name"]),
        )
    payload = body.model_dump()
    if len(json.dumps(payload, default=str)) > MAX_RUN_BYTES:
        raise HTTPException(status_code=413, detail=t("The run's options are too large."))
    try:
        answer = proxy.post_run(rt, app, kind, _person(caller), payload)
    except proxy.AppUnreachable as exc:
        raise HTTPException(
            status_code=503, detail=t("{app} does not answer. Try again in a moment.", app=app)
        ) from exc
    if answer.status >= 500:
        raise HTTPException(status_code=502, detail=t("{app} could not answer.", app=app))
    if answer.status < 300:
        rt.workspace.audit.record(
            caller.username,
            "notebooks.app_run",
            f"app:{app}",
            {"kind": kind, "id": body.id},
            app_id="processcraft",
        )
    return Response(content=answer.body, status_code=answer.status, media_type=answer.content_type)
