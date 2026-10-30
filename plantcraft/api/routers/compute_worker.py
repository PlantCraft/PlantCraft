"""The compute workers' side of the queue (docs/compute.md): enroll, take tasks, answer them.

A worker opens no port: it calls these routes, through the proxy's HTTPS from another machine
or straight from the internal network on this one. It proves itself with its own credential
(``Authorization: Bearer pcw_…``, given once at enrollment and kept here only hashed), which opens
these routes and nothing else of PlantCraft. A paused worker is answered but given no task; a
revoked one is refused.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from plantcraft.api.compute_io import save_body
from plantcraft.api.deps import Runtime
from plantcraft.api.identity import bearer_token
from plantcraft.compute import HEARTBEAT_SECONDS, LEASE_SECONDS, ComputeError, executor_name
from plantcraft.i18n import t

router = APIRouter(prefix="/api/compute-worker")

MAX_WAIT_SECONDS = 25.0
POLL_SECONDS = 0.25


def _worker(request: Request, rt: Runtime) -> dict[str, Any]:
    token = bearer_token(request)
    found = rt.compute.authenticate(token) if token else None
    if found is None:
        raise HTTPException(
            status_code=401,
            detail=t("This worker is not registered here, or it was revoked."),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return found


Worker = Annotated[dict[str, Any], Depends(_worker)]


def _http(error: ComputeError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


class Executor(BaseModel):
    app: str = Field(min_length=1, max_length=40)
    environment: str = Field(default="standard", max_length=40)
    version: str | None = Field(default=None, max_length=40)
    slots: int = Field(default=1, ge=0, le=256)
    free: int = Field(default=0, ge=0, le=256)
    memory_mb: float | None = Field(default=None, ge=0, le=1e8)


class Stats(BaseModel):
    cpus: float | None = Field(default=None, ge=0, le=4096)
    load: float | None = Field(default=None, ge=0, le=100000)
    memory_mb: float | None = Field(default=None, ge=0, le=1e8)
    memory_used_mb: float | None = Field(default=None, ge=0, le=1e8)
    version: str | None = Field(default=None, max_length=40)


class EnrollIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    host: str = Field(default="", max_length=120)
    executors: list[Executor] = Field(default_factory=list, max_length=32)


@router.post("/enroll")
def enroll(payload: EnrollIn, rt: Runtime) -> dict[str, Any]:
    """Trade the one-time code an administrator made for the worker's credential (once)."""

    try:
        worker, credential = rt.compute.enroll(
            payload.code,
            host=payload.host,
            executors=[item.model_dump() for item in payload.executors],
        )
    except ComputeError as error:
        raise _http(error) from error
    rt.workspace.audit.record(
        f"worker:{worker['id']}",
        "compute.worker.enroll",
        f"worker:{worker['id']}",
        {"name": worker["name"], "host": payload.host},
        app_id="processcraft",
    )
    return {
        "worker": worker,
        "credential": credential,
        "lease_seconds": LEASE_SECONDS,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
    }


class LeaseIn(BaseModel):
    executors: list[Executor] = Field(default_factory=list, max_length=32)
    stats: Stats = Field(default_factory=Stats)
    wait: float = Field(default=0.0, ge=0, le=MAX_WAIT_SECONDS)


@router.post("/lease")
async def lease(payload: LeaseIn, worker: Worker, rt: Runtime) -> dict[str, Any]:
    """Tasks for the executors with room (``free``), waiting up to ``wait`` seconds for one."""

    store = rt.compute
    executors = [item.model_dump() for item in payload.executors]
    await run_in_threadpool(
        lambda: store.seen(
            worker["id"], executors=executors, stats=payload.stats.model_dump(exclude_none=True)
        )
    )
    current = await run_in_threadpool(store.worker, worker["id"]) or worker
    free = {
        executor_name(item.app.strip().lower(), item.environment): item.free
        for item in payload.executors
        if item.free
    }
    deadline = time.monotonic() + payload.wait
    tasks: list[dict[str, Any]] = []
    while current.get("state") == "active" and free:
        if await run_in_threadpool(store.has_work, list(free)):
            tasks = await run_in_threadpool(store.lease, current, free)
            if tasks:
                break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(POLL_SECONDS)
    return {
        "state": current.get("state"),
        "tasks": [_given(task) for task in tasks],
        "lease_seconds": LEASE_SECONDS,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
    }


def _given(task: dict[str, Any]) -> dict[str, Any]:
    return {
        key: task[key]
        for key in (
            "id",
            "app",
            "environment",
            "size",
            "version",
            "kind",
            "timeout_seconds",
            "memory_mb",
            "input_bytes",
        )
    }


class HeartbeatIn(BaseModel):
    running: list[Annotated[str, Field(max_length=64)]] = Field(
        default_factory=list, max_length=1000
    )
    executors: list[Executor] | None = Field(default=None, max_length=32)
    stats: Stats = Field(default_factory=Stats)


@router.post("/heartbeat")
def heartbeat(payload: HeartbeatIn, worker: Worker, rt: Runtime) -> dict[str, Any]:
    """Keep the leases of the running tasks; ``stop`` names those the worker must drop."""

    executors = (
        None if payload.executors is None else [item.model_dump() for item in payload.executors]
    )
    rt.compute.seen(
        worker["id"], executors=executors, stats=payload.stats.model_dump(exclude_none=True)
    )
    stop = rt.compute.heartbeat(worker["id"], payload.running)
    current = rt.compute.worker(worker["id"]) or worker
    return {"state": current.get("state"), "stop": stop}


def _owned(worker: dict[str, Any], task_id: str, rt: Any) -> dict[str, Any]:
    if not task_id or len(task_id) > 64 or not task_id.isalnum():
        raise HTTPException(status_code=404, detail=t("Task not found."))
    found = rt.compute.owns(worker["id"], task_id)
    if found is None:
        raise HTTPException(status_code=409, detail=t("This task is no longer this worker's."))
    return found


@router.get("/tasks/{task_id}/input")
def task_input(task_id: str, worker: Worker, rt: Runtime) -> FileResponse:
    _owned(worker, task_id, rt)
    path = rt.compute.blob_path(task_id, "input")
    if path is None:
        raise HTTPException(status_code=410, detail=t("The task's input is gone."))
    return FileResponse(path, media_type="application/x-tar")


@router.post("/tasks/{task_id}/answer")
async def answer(
    task_id: str,
    request: Request,
    worker: Worker,
    rt: Runtime,
    status: Annotated[str, Query(max_length=10)] = "done",
    seconds: Annotated[float | None, Query(ge=0, le=1e7)] = None,
    error: Annotated[str, Query(max_length=1000)] = "",
) -> dict[str, Any]:
    """``done``: the body is the executor's answer (a tar archive); ``failed``: no answer came
    (``error`` says why) and the task goes back to the queue while it has tries left."""

    await run_in_threadpool(_owned, worker, task_id, rt)
    store = rt.compute
    size = None
    if status == "done":
        size = await save_body(request, store.folder / task_id / "output", store.max_bytes)
    try:
        found = await run_in_threadpool(
            lambda: store.finish(
                worker["id"], task_id, status=status, seconds=seconds, error=error,
                output_bytes=size,
            )
        )  # fmt: skip
    except ComputeError as exc:
        raise _http(exc) from exc
    return {"status": found.get("status")}
