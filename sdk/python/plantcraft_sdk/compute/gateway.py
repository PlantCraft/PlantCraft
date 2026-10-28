"""A compute worker's gateway: the one part of a worker that talks to PlantCraft.

It opens no port. It asks PlantCraft for tasks when the executors beside it have room, puts each
task in the executor's folder (``plantcraft_sdk.compute.folder``), sends the answer back, and
keeps the leases of what runs (a heartbeat every ``heartbeat_seconds``). The executors run the
code with no network and no secret; the gateway runs no code of a task, and keeps its credential
outside the job folders, where no executor can reach it.

First start on a new machine: ``--code`` (the one-time code from PlantCraft › Settings › Compute)
is traded for the worker's credential, written to ``--credential-file`` (mode 0600) and used
from then on::

    python -m plantcraft_sdk.compute gateway --platform https://plantcraft.example \\
        --jobs /jobs --credential-file /data/worker-credential --code pce_...

A task whose executor gives no answer within its time limit (plus a margin) is reported as failed,
and PlantCraft gives it to a worker again while it has tries left.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from plantcraft_sdk.compute import folder

LOGGER = logging.getLogger(__name__)
# Beyond a task's own time limit, how long the gateway waits for its executor's answer.
ANSWER_MARGIN_SECONDS = 30.0
HEALTH = "gateway.json"
LEASE_WAIT_SECONDS = 20.0
# The lease's wait while tasks run here: a slot that frees is filled at once, not after a long
# wait held for another executor's room (an idle Models kept Analytics' slots empty 20 s a time).
BUSY_WAIT_SECONDS = 1.0
IDLE_SECONDS = 0.5


class GatewayError(RuntimeError):
    """The gateway cannot start (no credential, a code PlantCraft refused)."""


@dataclass
class _Task:
    id: str
    app: str
    deadline: float
    started: float = field(default_factory=time.monotonic)
    stopped: bool = False


def machine_stats() -> dict[str, Any]:
    stats: dict[str, Any] = {"cpus": os.cpu_count() or 1}
    try:
        stats["load"] = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        pass
    try:
        values = {}
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for line in meminfo:
                name, _, rest = line.partition(":")
                values[name] = int(rest.split()[0])
        total = values.get("MemTotal", 0) / 1024
        stats["memory_mb"] = round(total)
        stats["memory_used_mb"] = round(total - values.get("MemAvailable", 0) / 1024)
    except (OSError, ValueError, IndexError):
        pass
    return stats


class Gateway:
    def __init__(
        self,
        platform: str,
        jobs: Path,
        credential: str,
        *,
        http: httpx.Client | None = None,
        max_bytes: int = folder.DEFAULT_MAX_BYTES,
    ):
        self.platform = platform.rstrip("/")
        self.jobs = jobs
        self.credential = credential
        self.http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))
        self.max_bytes = max_bytes
        self.running: dict[str, _Task] = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        # Set when a task's answer is sent: its slot is free for the next one at once.
        self.freed = threading.Event()
        self.heartbeat_seconds = 10.0
        self.state = "active"

    # PlantCraft ---------------------------------------------------------------------------------

    @staticmethod
    def enroll(
        platform: str,
        code: str,
        executors: list[dict[str, Any]],
        *,
        http: httpx.Client | None = None,
    ) -> str:
        """Trade the one-time code for the worker's credential."""

        client = http or httpx.Client(timeout=30.0)
        reply = client.post(
            f"{platform.rstrip('/')}/api/compute-worker/enroll",
            json={"code": code, "host": socket.gethostname(), "executors": executors},
        )
        if reply.status_code != 200:
            raise GatewayError(_detail(reply))
        return str(reply.json()["credential"])

    def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.credential}", **kwargs.pop("headers", {})}
        return self.http.post(f"{self.platform}{path}", headers=headers, **kwargs)

    def _get(self, path: str) -> httpx.Response:
        return self.http.get(
            f"{self.platform}{path}", headers={"Authorization": f"Bearer {self.credential}"}
        )

    # The executors beside it ----------------------------------------------------------------

    def executors(self) -> list[dict[str, Any]]:
        """Each executor with a fresh heartbeat: its app, environment, version, slots and room
        now (``app`` is the folder's name for the tasks it runs, ``executor_name``)."""

        found = []
        try:
            folders = sorted(path for path in self.jobs.iterdir() if path.is_dir())
        except OSError:
            return []
        with self.lock:
            busy: dict[str, int] = {}
            for task in self.running.values():
                busy[task.app] = busy.get(task.app, 0) + 1
        for app_dir in folders:
            beat = folder.heartbeat(app_dir)
            if beat is None:
                continue
            app = str(beat.get("app") or app_dir.name.partition(".")[0])
            environment = folder.environment_name(beat.get("environment"))
            name = folder.executor_name(app, environment)
            if not environment or name != app_dir.name:
                continue  # an executor answers only in its own app's folder
            try:
                slots = max(0, int(beat.get("workers") or 0))
            except (TypeError, ValueError):
                slots = 0
            found.append(
                {
                    "app": app,
                    "environment": environment,
                    "version": beat.get("version"),
                    "slots": slots,
                    "free": max(0, slots - busy.get(name, 0)),
                    # The memory one task may use there (the executor's --memory-mb).
                    "memory_mb": beat.get("memory_mb"),
                }
            )
        return found

    # The loops ---------------------------------------------------------------------------------

    def take(self) -> int:
        """One lease call (waiting when there is room); the tasks placed."""

        self.freed.clear()
        executors = self.executors()
        if self.state != "active" or not any(item["free"] for item in executors):
            # Full, or paused: the heartbeat keeps PlantCraft informed meanwhile. A task that
            # ends wakes it, so its slot takes the next task without a pause.
            self.freed.wait(IDLE_SECONDS)
            return 0
        with self.lock:
            wait = BUSY_WAIT_SECONDS if self.running else LEASE_WAIT_SECONDS
        reply = self._post(
            "/api/compute-worker/lease",
            json={"executors": executors, "stats": machine_stats(), "wait": wait},
            timeout=wait + 30,
        )
        if reply.status_code == 401:
            raise GatewayError(_detail(reply))
        if reply.status_code != 200:
            LOGGER.warning("lease: %s %s", reply.status_code, _detail(reply))
            self.stop.wait(5)
            return 0
        answer = reply.json()
        self.state = str(answer.get("state") or "active")
        self.heartbeat_seconds = float(answer.get("heartbeat_seconds") or 10)
        placed = 0
        for task in answer.get("tasks") or []:
            if self.place(task):
                placed += 1
        return placed

    def place(self, task: dict[str, Any]) -> bool:
        task_id = str(task["id"])
        # The folder of the executor that runs it: the task's app, in its environment.
        app = folder.executor_name(str(task["app"]), task.get("environment"))
        app_dir = self.jobs / app
        timeout = float(task.get("timeout_seconds") or 300)
        with self.lock:
            self.running[task_id] = _Task(
                task_id, app, time.monotonic() + timeout + ANSWER_MARGIN_SECONDS
            )
        incoming = app_dir / f".incoming-{task_id}"
        try:
            reply = self._get(f"/api/compute-worker/tasks/{task_id}/input")
            if reply.status_code != 200:
                raise folder.ArchiveError(_detail(reply))
            shutil.rmtree(incoming, ignore_errors=True)
            folder.unpack(reply.content, incoming, max_bytes=self.max_bytes)
            folder.write_json(
                incoming / folder.TASK,
                {
                    "id": task_id,
                    "kind": task.get("kind"),
                    "size": task.get("size"),
                    "timeout_seconds": timeout,
                    "memory_mb": task.get("memory_mb"),
                },
            )
            incoming.rename(app_dir / folder.QUEUE / task_id)
        except (folder.ArchiveError, OSError, httpx.HTTPError) as exc:
            shutil.rmtree(incoming, ignore_errors=True)
            self.report(task_id, "failed", error=f"the worker could not take the task: {exc}")
            return False
        return True

    def report(self, task_id: str, status: str, *, error: str = "", body: bytes = b"") -> None:
        with self.lock:
            task = self.running.pop(task_id, None)
        self.freed.set()
        seconds = round(time.monotonic() - task.started, 3) if task else None
        params: dict[str, Any] = {"status": status, "error": error[:900]}
        if seconds is not None:
            params["seconds"] = seconds
        try:
            reply = self._post(
                f"/api/compute-worker/tasks/{task_id}/answer",
                params=params,
                content=body,
                headers={"Content-Type": "application/octet-stream"},
            )
            if reply.status_code not in (200, 409):
                LOGGER.warning("answer %s: %s %s", task_id, reply.status_code, _detail(reply))
        except httpx.HTTPError as exc:
            # The lease runs out and PlantCraft gives the task to a worker again.
            LOGGER.warning("answer %s could not be sent: %s", task_id, exc)

    def collect(self) -> int:
        """Send the answers the executors wrote; report the tasks past their deadline."""

        with self.lock:
            tasks = list(self.running.values())
        sent = 0
        now = time.monotonic()
        # An executor that stopped (its heartbeat is older than STALE_SECONDS) runs nothing:
        # its tasks go back to PlantCraft's queue for another worker, not wait for their time.
        silent = {task.app for task in tasks if folder.heartbeat(self.jobs / task.app) is None}
        for task in tasks:
            app_dir = self.jobs / task.app
            done = app_dir / folder.DONE / task.id
            if task.app in silent and not task.stopped and not done.is_dir():
                self._cancel_files(task)
                self.report(task.id, "failed", error=f"the executor of {task.app} stopped")
                continue
            if task.stopped:
                if done.exists() or now > task.deadline:
                    shutil.rmtree(done, ignore_errors=True)
                    with self.lock:
                        self.running.pop(task.id, None)
                continue
            if done.is_dir() and (done / folder.RESULT).exists():
                try:
                    body = folder.pack_answer(done, max_bytes=self.max_bytes)
                except (folder.ArchiveError, OSError) as exc:
                    self.report(task.id, "failed", error=str(exc))
                else:
                    self.report(task.id, "done", body=body)
                shutil.rmtree(done, ignore_errors=True)
                sent += 1
            elif now > task.deadline:
                self._cancel_files(task)
                self.report(task.id, "failed", error="no answer from the executor in time")
        return sent

    def _cancel_files(self, task: _Task) -> None:
        app_dir = self.jobs / task.app
        shutil.rmtree(app_dir / folder.QUEUE / task.id, ignore_errors=True)
        work = app_dir / folder.WORK / task.id
        if work.is_dir():
            try:
                (work / folder.CANCEL).write_text("", encoding="utf-8")
            except OSError:
                pass

    def beat(self) -> None:
        with self.lock:
            running = [task.id for task in self.running.values() if not task.stopped]
        try:
            reply = self._post(
                "/api/compute-worker/heartbeat",
                json={
                    "running": running,
                    "executors": self.executors(),
                    "stats": machine_stats(),
                },
            )
        except httpx.HTTPError as exc:
            LOGGER.warning("heartbeat: %s", exc)
            return
        if reply.status_code == 401:
            LOGGER.error("PlantCraft refused this worker: %s", _detail(reply))
            self.stop.set()
            return
        if reply.status_code != 200:
            return
        answer = reply.json()
        self.state = str(answer.get("state") or self.state)
        # PlantCraft answered: the container's healthcheck reads this file.
        folder.write_json(self.jobs / HEALTH, {"state": self.state, "at": time.time()})
        for task_id in answer.get("stop") or []:
            with self.lock:
                task = self.running.get(task_id)
                if task is not None:
                    task.stopped = True
                    task.deadline = time.monotonic() + ANSWER_MARGIN_SECONDS
            if task is not None:
                self._cancel_files(task)

    def _collector(self) -> None:
        while not self.stop.wait(0.1):
            try:
                self.collect()
            except Exception:  # noqa: BLE001 - the next pass tries again
                LOGGER.exception("collect failed")

    def _heart(self) -> None:
        while not self.stop.wait(self.heartbeat_seconds):
            try:
                self.beat()
            except Exception:  # noqa: BLE001
                LOGGER.exception("heartbeat failed")

    def clear(self) -> None:
        """At start: what a previous gateway left in the folders is not this one's to answer."""

        for app_dir in (path for path in self.jobs.iterdir() if path.is_dir()):
            folder.prepare(app_dir)
            for entry in app_dir.iterdir():
                if entry.name.startswith(".incoming-"):
                    shutil.rmtree(entry, ignore_errors=True)
            for name in (folder.QUEUE, folder.DONE):
                for entry in (app_dir / name).iterdir():
                    shutil.rmtree(entry, ignore_errors=True)
            for entry in (app_dir / folder.WORK).iterdir():
                try:
                    (entry / folder.CANCEL).write_text("", encoding="utf-8")
                except OSError:
                    pass

    def serve(self) -> None:
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.clear()
        threads = [
            threading.Thread(target=self._collector, name="collect", daemon=True),
            threading.Thread(target=self._heart, name="heartbeat", daemon=True),
        ]
        for thread in threads:
            thread.start()
        failures = 0
        while not self.stop.is_set():
            try:
                self.take()
                failures = 0
            except GatewayError:
                LOGGER.error("PlantCraft refused this worker: stopping.")
                self.stop.set()
                raise
            except httpx.HTTPError as exc:
                failures += 1
                pause = min(30.0, 2.0**failures)
                LOGGER.warning("PlantCraft cannot be reached (%s): again in %.0f s", exc, pause)
                self.stop.wait(pause)


def _detail(reply: httpx.Response) -> str:
    try:
        detail = reply.json().get("detail")
    except ValueError:
        detail = None
    return str(detail or reply.text[:300] or reply.status_code)


__all__ = ["Gateway", "GatewayError", "machine_stats"]
