"""API v1: the apps hand tasks to the suite's compute workers (docs/compute.md).

Only an app's own token sends tasks (``write.compute`` in its ``[permissions]``), and an app sees
only its own tasks. A task's input is the request body (a tar archive of the job folder its
executor reads, at most ``PLANTCRAFT_COMPUTE_MAX_MB``); PlantCraft never opens it. The answer
is the archive the worker sent back, read once and then dropped (``DELETE``).
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from processcraft.api.compute_io import save_body
from processcraft.api.deps import Runtime
from processcraft.api.identity import Caller, V1Caller
from processcraft.compute import FINISHED, PRIORITIES, ComputeError
from processcraft.i18n import t

router = APIRouter(prefix="/api/v1/compute")

MAX_WAIT_SECONDS = 25.0
POLL_SECONDS = 0.2


def _app(caller: Caller) -> str:
    if not caller.app_id:
        raise HTTPException(
            status_code=403, detail=t("Only an app's own token sends tasks to the workers.")
        )
    return caller.app_id


def _http(error: ComputeError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


def _clean_id(task_id: str) -> str:
    if not task_id or len(task_id) > 64 or not task_id.isalnum():
        raise HTTPException(status_code=404, detail=t("Task not found."))
    return task_id


@router.post("/tasks", status_code=201)
async def submit(
    request: Request,
    caller: V1Caller,
    rt: Runtime,
    kind: Annotated[str, Query(max_length=60)] = "",
    priority: Annotated[str, Query(max_length=20)] = "run",
    version: Annotated[str | None, Query(max_length=40)] = None,
    labels: Annotated[str, Query(max_length=400)] = "",
    run: Annotated[str | None, Query(max_length=200)] = None,
    timeout_seconds: Annotated[float | None, Query(gt=0, le=6 * 3600)] = None,
    memory_mb: Annotated[int | None, Query(ge=64, le=64 * 1024)] = None,
    environment: Annotated[str | None, Query(max_length=40)] = None,
    size: Annotated[str | None, Query(max_length=20)] = None,
) -> dict[str, Any]:
    """Queue a task: the body is its input (``application/octet-stream``). ``environment``
    and ``size`` say where it may run (docs/compute.md)."""

    app = _app(caller)
    if priority not in PRIORITIES:
        raise HTTPException(
            status_code=422, detail=t("priority is one of {names}.", names=", ".join(PRIORITIES))
        )
    store = rt.compute
    task_id = store.new_task_id()
    received = await save_body(request, store.folder / task_id / "input", store.max_bytes)
    if not received:
        await run_in_threadpool(store.collected, task_id, app_id=app)
        raise HTTPException(status_code=422, detail=t("The task has no input."))
    try:
        return await run_in_threadpool(
            lambda: store.submit(
                task_id,
                app_id=app,
                version=version,
                kind=kind,
                priority=priority,
                labels=[item for item in labels.split(",") if item.strip()],
                run_id=run,
                timeout_seconds=timeout_seconds,
                memory_mb=memory_mb,
                input_bytes=received,
                environment=environment,
                size=size,
            )
        )
    except ComputeError as error:
        raise _http(error) from error


@router.get("/tasks/{task_id}")
def task(task_id: str, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    found = rt.compute.task(_clean_id(task_id), app_id=_app(caller))
    if found is None:
        raise HTTPException(status_code=404, detail=t("Task not found."))
    return found


class WaitIn(BaseModel):
    ids: list[Annotated[str, Field(max_length=64)]] = Field(min_length=1, max_length=500)
    seconds: float = Field(default=20.0, ge=0, le=MAX_WAIT_SECONDS)


@router.post("/wait")
async def wait(payload: WaitIn, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """The tasks, as soon as one of them has finished (or after ``seconds``)."""

    app = _app(caller)
    ids = list(dict.fromkeys(payload.ids))
    deadline = time.monotonic() + payload.seconds
    while True:
        found = await run_in_threadpool(rt.compute.tasks, ids, app_id=app)
        if any(item["status"] in FINISHED for item in found) or len(found) < len(ids):
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(POLL_SECONDS)
    known = {item["id"] for item in found}
    return {"tasks": found, "unknown": [item for item in ids if item not in known]}


@router.get("/tasks/{task_id}/output")
def output(task_id: str, caller: V1Caller, rt: Runtime) -> FileResponse:
    """The worker's answer (a tar archive), until the app drops it (``DELETE``) or an hour on."""

    task_id = _clean_id(task_id)
    found = rt.compute.task(task_id, app_id=_app(caller))
    if found is None:
        raise HTTPException(status_code=404, detail=t("Task not found."))
    if found["status"] != "done":
        raise HTTPException(status_code=409, detail=t("This task has no answer."))
    path = rt.compute.blob_path(task_id, "output")
    if path is None:
        raise HTTPException(status_code=410, detail=t("The answer was already collected."))
    return FileResponse(path, media_type="application/x-tar")


@router.post("/tasks/{task_id}/cancel")
def cancel(task_id: str, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    found = rt.compute.cancel(_clean_id(task_id), app_id=_app(caller))
    if found is None:
        raise HTTPException(status_code=404, detail=t("Task not found."))
    return found


@router.delete("/tasks/{task_id}")
def collected(task_id: str, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """The app has what it needs: the task's bytes go now."""

    if not rt.compute.collected(_clean_id(task_id), app_id=_app(caller)):
        raise HTTPException(status_code=404, detail=t("Task not found."))
    return {"collected": True}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """Every task of one of the app's runs that waits or runs (the person cancelled the run)."""

    return {"cancelled": rt.compute.cancel_run(run_id[:200], app_id=_app(caller))}


@router.get("/capacity")
def capacity(
    caller: V1Caller,
    rt: Runtime,
    version: Annotated[str | None, Query(max_length=40)] = None,
    environment: Annotated[str | None, Query(max_length=40)] = None,
    size: Annotated[str | None, Query(max_length=20)] = None,
) -> dict[str, Any]:
    """How many workers online run this app's tasks (in an environment, with room for a size),
    what waits, and the environments and sizes on offer: an app says "waiting for a compute
    worker" when there is none."""

    return rt.compute.capacity(_app(caller), version, environment=environment, size=size)
