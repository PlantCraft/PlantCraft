"""HTTP routes: the plant map file (template, export, preview and import).

The file holds sources, assets, signals and each application's objects
(``plantcraft/platform/plantmap.py``). Uploads are sent as the request body
with the file name in the query, so no multipart parser is needed. The routes read the body
asynchronously and then plan or import in a worker thread: checking an OPC UA source's tags
browses it with its own event loop, which cannot run inside the server's.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from plantcraft.api.deps import AdminUser, CurrentUser, Runtime
from plantcraft.i18n import t
from plantcraft.platform import plantmap
from plantcraft.platform.datalayer import DataLayerError

router = APIRouter(prefix="/api/map")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download(rt: Any, payload: dict[str, Any], name: str, kind: str) -> Response:
    if kind == "xlsx":
        try:
            content = plantmap.workbook(rt.platform, payload)
        except plantmap.MapError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        media = XLSX
    else:
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        media = "application/json"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}.{kind}"'},
    )


@router.get("/format")
def map_format(_user: CurrentUser, rt: Runtime) -> list[dict[str, Any]]:
    """Every section and column of the file, with what each one means."""

    return plantmap.format_reference(rt.platform)


@router.get("/template.{kind}")
def map_template(kind: str, _user: CurrentUser, rt: Runtime) -> Response:
    if kind not in {"json", "xlsx"}:
        raise HTTPException(status_code=404, detail=t("Unknown format."))
    return _download(rt, plantmap.template(rt.platform), "plant-map-template", kind)


@router.get("/export.{kind}")
def map_export(kind: str, _user: CurrentUser, rt: Runtime) -> Response:
    if kind not in {"json", "xlsx"}:
        raise HTTPException(status_code=404, detail=t("Unknown format."))
    return _download(rt, plantmap.export(rt.platform), "plant-map", kind)


async def _body(request: Request) -> bytes:
    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail=t("Send the map file."))
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=t("The file is larger than 10 MB."))
    return content


@router.post("/preview")
async def map_preview(
    request: Request,
    _user: CurrentUser,
    rt: Runtime,
    filename: str = Query(min_length=1, max_length=200),
    prune: bool = False,
) -> dict[str, Any]:
    """What importing the file would create, update or remove, and every problem by sheet and line."""

    content = await _body(request)
    try:
        report, _changes = await run_in_threadpool(
            plantmap.plan, rt.platform, content, filename, prune=prune
        )
    except plantmap.MapError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return report


@router.post("/apply")
async def map_apply(
    request: Request,
    user: AdminUser,
    rt: Runtime,
    filename: str = Query(min_length=1, max_length=200),
    prune: bool = False,
) -> dict[str, Any]:
    """Import the file; nothing changes when it has errors. Importing it again changes nothing."""

    content = await _body(request)
    return await run_in_threadpool(_apply, rt, content, filename, prune, user)


def _apply(rt: Any, content: bytes, filename: str, prune: bool, user: str) -> dict[str, Any]:
    try:
        result = plantmap.apply(rt.platform, content, filename, prune=prune, actor=user)
    except plantmap.MapError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataLayerError as exc:  # HistCraft refused or did not answer a source change
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    if result["applied"]:
        rt.sync_assets()
        changed = sum(
            item["create"] + item["update"] + item["remove"] for item in result["sections"]
        )
        if changed:
            rt.platform.publish(
                "map.imported",
                f"asset:{rt.platform.root_asset_id}",
                source="platform",
                actor=user,
                summary=t(
                    "Plant map imported ({file}): {count} changes.",
                    file=result["file"],
                    count=changed,
                ),
            )
    return result
