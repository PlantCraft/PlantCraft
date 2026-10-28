"""An app's side of the suite's compute: hand tasks to the workers and read their answers.

The app reads the data a task needs with its own token, packs a job folder (``job.json`` and
its files) and submits it; a worker runs it in the app's executor and the answer comes back as
``result.json`` and the files under ``out/``. The app needs ``write.compute`` in its
``app.toml`` ``[permissions]`` and an executor of its own version on some worker::

    compute = ComputeClient(client, version="0.5.0")
    task = compute.submit({"job.json": json.dumps(job), "data.npz": data}, kind="analyse")
    for answer in compute.answers([task]):
        print(answer.result, answer.files.keys())

``answers`` yields each task as it finishes (failed and cancelled ones too, with
``answer.error``), and drops its bytes from PlantCraft once read.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from plantcraft_sdk.client import PlantCraftClient, Unavailable, _error
from plantcraft_sdk.compute import folder

FINISHED = ("done", "failed", "cancelled")
WAIT_SECONDS = 20.0
# PlantCraft restarting (an update, a recreated container) cuts the long poll: waiting goes on
# for this long before the tasks are given up as unreachable.
OUTAGE_SECONDS = 300.0


@dataclass
class Answer:
    """A finished task: ``status`` (done, failed, cancelled), the executor's ``result.json`` and
    the files it wrote under ``out/`` (``out/`` left out of the names)."""

    id: str
    status: str
    result: dict[str, Any] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)
    error: str = ""
    task: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "done" and self.result.get("status", "done") == "done"


class ComputeClient:
    def __init__(self, client: PlantCraftClient, *, version: str | None = None):
        self.client = client
        self.version = version

    def _url(self, path: str) -> str:
        return f"{self.client.base_url}/api/v1/compute{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.client.token()}", **kwargs.pop("headers", {})}
        try:
            response = self.client.http.request(method, self._url(path), headers=headers, **kwargs)
        except Exception as exc:  # httpx.TransportError and friends
            raise Unavailable(f"PlantCraft could not be reached: {exc}") from exc
        if response.is_error:
            raise _error(response)
        return response

    def submit(
        self,
        files: Mapping[str, bytes | str] | bytes,
        *,
        kind: str = "",
        priority: str = "run",
        run: str | None = None,
        labels: Iterable[str] = (),
        timeout_seconds: float | None = None,
        memory_mb: int | None = None,
        environment: str | None = None,
        size: str | None = None,
    ) -> str:
        """Queue a task (a job folder, or an archive already packed); its id.

        ``environment`` (``standard`` by default) is the executor's image it needs, ``size``
        (``small``, ``medium``, ``large``) the machine it needs room on (docs/compute.md).
        """

        body = files if isinstance(files, bytes) else folder.pack(files)
        params = {
            "kind": kind,
            "priority": priority,
            "version": self.version,
            "labels": ",".join(labels),
            "environment": environment,
            "size": size,
            "run": run,
            "timeout_seconds": timeout_seconds,
            "memory_mb": memory_mb,
        }
        response = self._request(
            "POST",
            "/tasks",
            params={key: value for key, value in params.items() if value not in (None, "")},
            content=body,
            headers={"Content-Type": "application/octet-stream"},
            timeout=120.0,
        )
        return str(response.json()["id"])

    def task(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/tasks/{task_id}").json()

    def wait(self, ids: list[str], seconds: float = WAIT_SECONDS) -> list[dict[str, Any]]:
        """The tasks, as soon as one has finished (or after ``seconds``)."""

        response = self._request(
            "POST", "/wait", json={"ids": ids[:500], "seconds": seconds}, timeout=seconds + 30
        )
        found = response.json()
        lost = [
            {"id": task_id, "status": "failed", "error": "PlantCraft no longer knows this task"}
            for task_id in found.get("unknown") or []
        ]
        return list(found.get("tasks") or []) + lost

    def answer(self, task: dict[str, Any]) -> Answer:
        """The answer of a finished task; its bytes are dropped from PlantCraft once read."""

        task_id = str(task["id"])
        if task.get("status") != "done":
            self._forget(task_id)
            return Answer(
                task_id, str(task.get("status")), error=str(task.get("error") or ""), task=task
            )
        data = self._request("GET", f"/tasks/{task_id}/output", timeout=120.0).content
        self._forget(task_id)
        files = folder.read(data)
        try:
            result = json.loads(files.pop(folder.RESULT, b"{}") or b"{}")
        except ValueError:
            result = {"status": "error", "error": "the executor's result.json is not JSON"}
        if not isinstance(result, dict):
            result = {"status": "error", "error": "the executor's result.json is not an object"}
        prefix = f"{folder.OUT}/"
        out = {
            name[len(prefix) :]: content
            for name, content in files.items()
            if name.startswith(prefix)
        }
        error = "" if result.get("status", "done") == "done" else str(result.get("error") or "")
        return Answer(task_id, "done", result, out, error, task)

    def _forget(self, task_id: str) -> None:
        try:
            self._request("DELETE", f"/tasks/{task_id}")
        except Exception:  # noqa: BLE001 - PlantCraft drops it after an hour anyway
            pass

    def answers(self, ids: Iterable[str], *, timeout: float | None = None) -> Iterator[Answer]:
        """Each task's answer as it finishes; after ``timeout`` seconds the rest are cancelled
        and come back as ``cancelled``."""

        pending = list(dict.fromkeys(ids))
        deadline = None if timeout is None else time.monotonic() + timeout
        down_since: float | None = None
        failures = 0
        while pending:
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                for task_id in pending:
                    found = self.cancel(task_id)
                    yield Answer(task_id, "cancelled", error="no answer in time", task=found)
                return
            seconds = WAIT_SECONDS if left is None else max(0.0, min(WAIT_SECONDS, left))
            finished = []
            try:
                for start in range(0, len(pending), 500):
                    chunk = pending[start : start + 500]
                    tasks = self.wait(chunk, seconds if start == 0 else 0)
                    finished += [task for task in tasks if task.get("status") in FINISHED]
            except Unavailable:
                # The tasks live in PlantCraft's database: once it is back, they are still there.
                now = time.monotonic()
                down_since = down_since or now
                if now - down_since > OUTAGE_SECONDS:
                    raise
                failures += 1
                time.sleep(min(10.0, 0.5 * 2**failures, max(0.1, left or 10.0)))
                continue
            down_since, failures = None, 0
            for task in finished:
                pending.remove(str(task["id"]))
                yield self.answer(task)

    def run(self, files: Mapping[str, bytes | str] | bytes, **options: Any) -> Answer:
        """Submit one task and wait for its answer (``timeout`` bounds the wait)."""

        timeout = options.pop("timeout", None)
        task_id = self.submit(files, **options)
        return next(self.answers([task_id], timeout=timeout))

    def cancel(self, task_id: str) -> dict[str, Any]:
        return self._request("POST", f"/tasks/{task_id}/cancel").json()

    def cancel_run(self, run: str) -> int:
        return int(self._request("POST", f"/runs/{run}/cancel").json().get("cancelled") or 0)

    def capacity(
        self, *, environment: str | None = None, size: str | None = None
    ) -> dict[str, Any]:
        """Workers online that run this app's tasks (of its version; in ``environment``, with
        room for ``size`` when given), what waits, and the environments and sizes on offer."""

        params = {"version": self.version, "environment": environment, "size": size}
        return self._request(
            "GET", "/capacity", params={key: value for key, value in params.items() if value}
        ).json()


__all__ = ["Answer", "ComputeClient"]
