"""Settings › Compute (administrators): the compute workers and what they run (docs/compute.md).

An administrator adds a worker (a name and labels): PlantCraft answers a one-time code, valid
for 15 minutes, that the worker's machine trades for its own credential (``install.sh --worker``).
From here a worker is paused (it ends what it runs and takes nothing more), resumed or revoked,
and each app gets its limits per task (time and memory). Every change is in the audit log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from processcraft.api.deps import AdminUser, CurrentUser, Runtime
from processcraft.compute import ENROLL_MINUTES, ComputeError
from processcraft.i18n import t

router = APIRouter(prefix="/api/compute")


def _http(error: ComputeError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


def _audit(rt: Any, admin: str, action: str, worker: dict[str, Any], **detail: Any) -> None:
    rt.workspace.audit.record(
        admin,
        action,
        f"worker:{worker.get('id')}",
        {"name": worker.get("name"), **detail},
        app_id="processcraft",
    )


@router.get("")
def overview(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The workers (state, executors, numbers of the last 24 h), the queue per app, the limits."""

    found = rt.compute.overview()
    found["apps"] = [{"id": app.id, "name": app.name} for app in rt.suite_apps()]
    return found


@router.get("/summary")
def summary(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """The workers per app as anyone signed in sees them (the Queue panel): names, states,
    environments, slots and what runs; no host, label or credential."""

    return rt.compute.summary()


class WorkerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    labels: list[str] = Field(default_factory=list, max_length=20)


def _enrollment(request: Request, worker: dict[str, Any], code: str) -> dict[str, Any]:
    # The address the administrator reached PlantCraft at is the one the worker calls.
    address = str(request.base_url).rstrip("/")
    return {
        "worker": worker,
        "code": code,
        "expires_minutes": ENROLL_MINUTES,
        "platform_url": address,
        "command": f"./install.sh --worker --platform {address} --code {code}",
    }


@router.post("/workers", status_code=201)
def add_worker(
    payload: WorkerIn, request: Request, admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    """A worker waiting for its machine, and the one-time code (in this answer only)."""

    try:
        worker, code = rt.compute.create_worker(payload.name, labels=payload.labels, actor=admin)
    except ComputeError as error:
        raise _http(error) from error
    _audit(rt, admin, "compute.worker.create", worker, labels=worker["labels"])
    return _enrollment(request, worker, code)


@router.post("/workers/{worker_id}/code")
def new_code(worker_id: str, request: Request, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A new one-time code for a worker whose machine did not enroll in time."""

    worker = rt.compute.worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail=t("Worker not found."))
    try:
        code = rt.compute.renew_code(worker_id)
    except ComputeError as error:
        raise _http(error) from error
    _audit(rt, admin, "compute.worker.code", worker)
    return _enrollment(request, rt.compute.worker(worker_id) or worker, code)


def _set_state(worker_id: str, state: str, admin: str, rt: Any) -> dict[str, Any]:
    try:
        worker = rt.compute.set_state(worker_id, state)
    except ComputeError as error:
        raise _http(error) from error
    action = "resume" if state == "active" else state.removesuffix("d")
    _audit(rt, admin, f"compute.worker.{action}", worker)
    return worker


@router.post("/workers/{worker_id}/pause")
def pause(worker_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """It ends what it runs and takes no new task."""

    return _set_state(worker_id, "paused", admin, rt)


@router.post("/workers/{worker_id}/resume")
def resume(worker_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    return _set_state(worker_id, "active", admin, rt)


@router.post("/workers/{worker_id}/revoke")
def revoke(worker_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Its credential stops working at once; what it ran goes back to the queue."""

    return _set_state(worker_id, "revoked", admin, rt)


@router.delete("/workers/{worker_id}")
def remove(worker_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    worker = rt.compute.worker(worker_id)
    try:
        removed = rt.compute.remove_worker(worker_id)
    except ComputeError as error:
        raise _http(error) from error
    if not removed or worker is None:
        raise HTTPException(status_code=404, detail=t("Worker not found."))
    _audit(rt, admin, "compute.worker.remove", worker)
    return {"removed": True}


class LimitsIn(BaseModel):
    timeout_seconds: float | None = Field(default=None, gt=0, le=6 * 3600)
    memory_mb: int | None = Field(default=None, ge=64, le=64 * 1024)


@router.put("/limits/{app_id}")
def set_limits(app_id: str, payload: LimitsIn, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The most time and memory one task of the app may take (empty: the suite's defaults)."""

    known = {app.id for app in rt.suite_apps()}
    if app_id not in known:
        raise HTTPException(status_code=404, detail=t("App not found."))
    try:
        found = rt.compute.set_limits(
            app_id,
            timeout_seconds=payload.timeout_seconds,
            memory_mb=payload.memory_mb,
            actor=admin,
        )
    except ComputeError as error:
        raise _http(error) from error
    rt.workspace.audit.record(
        admin,
        "compute.limits",
        f"app:{app_id}",
        payload.model_dump(),
        app_id="processcraft",
    )
    return found
