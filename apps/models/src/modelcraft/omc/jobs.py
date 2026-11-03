"""Handing jobs to the Modelica runner and collecting its answers.

``SuiteExecutor`` is the suite's way: each job is a task of PlantCraft's compute workers
(PlantCraft docs/compute.md), answered by the runner (no network, no secret) on this machine or
another. ``QueueExecutor`` hands the job to a runner through a folder shared with it, with no
PlantCraft in between. ``LocalExecutor`` runs the same runner code on this process's machine,
for development where ``omc`` is installed; it is never the default. All answer a ``JobAnswer``
whose files sit in a folder the caller owns until ``close()``.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.compute.client import ComputeClient
from plantcraft_sdk.files import write_json

from modelcraft.i18n import t
from modelcraft.omc import runner
from modelcraft.omc.messages import parse, simulation_log

HEARTBEAT_SECONDS = 60
# What the runner may take before the job counts as lost: its own time limit plus the queue.
GRACE_SECONDS = 120
# On the compute workers, how long a job may also wait for a free runner.
QUEUE_SECONDS = 900
# The tasks ask for runners of this protocol (their heartbeat's ``version``).
SUITE_VERSION = f"runner-{runner.RUNNER_VERSION}"
CAPACITY_SECONDS = 5.0


class RunnerUnavailable(RuntimeError):
    """No runner answered: the job was not run."""


@dataclass
class JobAnswer:
    status: str  # done | timeout | cancelled | refused | error
    seconds: float = 0.0
    steps: dict[str, str] = field(default_factory=dict)
    log: str = ""
    error: str = ""
    folder: Path | None = None
    # A sweep's time for each variant (None where the runner could not tell).
    variant_seconds: list[float | None] = field(default_factory=list)

    def ok(self, step: str) -> bool:
        return self.steps.get(f"{step}.ok", "").strip() not in ("", "false")

    def text(self, step: str) -> str:
        return self.steps.get(f"{step}.ok", "")

    def file(self, name: str) -> Path | None:
        if self.folder is None:
            return None
        path = self.folder / "out" / name
        return path if path.is_file() else None

    def messages(self) -> list[dict[str, Any]]:
        """Every step's messages, in the order omc ran them; the simulation's own log last."""

        found: list[dict[str, Any]] = []
        seen: set[tuple] = set()
        for name in sorted(self.steps, key=_step_order):
            if name.endswith(".err"):
                for message in parse(self.steps[name]):
                    key = (message["level"], message["text"], message.get("line"))
                    if key not in seen:
                        seen.add(key)
                        found.append(message)
        if "simulate.msg" in self.steps:
            found.extend(simulation_log(self.steps["simulate.msg"]))
        if self.status == "timeout":
            found.append(
                {
                    "level": "error",
                    "text": t("The job took longer than its time limit."),
                    "file": None,
                }
            )
        if self.status == "cancelled":
            found.append({"level": "warning", "text": "Cancelled.", "file": None})
        if self.status in ("refused", "error") and self.error:
            found.append({"level": "error", "text": self.error, "file": None})
        return found

    def close(self) -> None:
        if self.folder is not None:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.folder = None


def _step_order(name: str) -> tuple[int, str]:
    order = ("load-", "file-", "check", "instance", "simulate", "build", "variant-", "fmu", "index")
    for index, prefix in enumerate(order):
        if name.startswith(prefix):
            return index, name
    return len(order), name


def new_job_id() -> str:
    return f"{time.strftime('%Y%m%d%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:12]}"


class Executor(Protocol):
    def run(
        self,
        job: dict[str, Any],
        files: dict[str, str],
        *,
        timeout: float,
        extra: dict[str, bytes] | None = None,
        job_id: str | None = None,
    ) -> JobAnswer: ...

    def state(self) -> dict[str, Any]: ...

    def cancel(self, job_id: str) -> None: ...

    def output(self, job_id: str, name: str) -> Path | None: ...


def _write_job(
    folder: Path, job: dict[str, Any], files: dict[str, str], extra: dict[str, bytes]
) -> None:
    (folder / "files").mkdir(parents=True)
    for path, text in files.items():
        target = (folder / "files" / path).resolve()
        if folder / "files" not in target.parents:
            raise ValueError(f"file outside the project: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for name, content in extra.items():
        (folder / name).write_bytes(content)
    write_json(folder / "job.json", job)


def _answer(folder: Path) -> JobAnswer:
    try:
        data = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"status": "error", "error": t("The runner gave no answer.")}
    return JobAnswer(
        status=str(data.get("status", "error")),
        seconds=float(data.get("seconds") or 0.0),
        steps={str(k): str(v) for k, v in (data.get("steps") or {}).items()},
        log=str(data.get("log") or ""),
        error=str(data.get("error") or ""),
        folder=folder,
        variant_seconds=[
            float(item) if isinstance(item, (int, float)) else None
            for item in (data.get("variant_seconds") or [])
        ],
    )


class QueueExecutor:
    """The runner container, through the shared jobs folder."""

    def __init__(self, jobs_dir: Path, *, poll_seconds: float = 0.1):
        self.jobs_dir = jobs_dir
        self.poll_seconds = poll_seconds
        for name in ("stage", "queue", "work", "done", "collected"):
            (jobs_dir / name).mkdir(parents=True, exist_ok=True)

    def state(self) -> dict[str, Any]:
        try:
            data = json.loads((self.jobs_dir / "runner.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"available": False, "reason": t("The Modelica runner has not started.")}
        age = time.time() - float(data.get("at") or 0)
        available = age < HEARTBEAT_SECONDS
        return {
            "available": available,
            "reason": "" if available else t("The Modelica runner stopped answering."),
            "omc": data.get("omc", ""),
            "libraries": data.get("libraries", {}),
            "workers": data.get("workers"),
            "queued": sum(1 for _ in (self.jobs_dir / "queue").iterdir()),
            "running": sum(1 for _ in (self.jobs_dir / "work").iterdir()),
        }

    def run(
        self,
        job: dict[str, Any],
        files: dict[str, str],
        *,
        timeout: float,
        extra: dict[str, bytes] | None = None,
        job_id: str | None = None,
    ) -> JobAnswer:
        state = self.state()
        if not state["available"]:
            raise RunnerUnavailable(state["reason"])
        job_id = job_id or new_job_id()
        stage = self.jobs_dir / "stage" / job_id
        _write_job(stage, {**job, "id": job_id, "timeout": timeout}, files, extra or {})
        stage.rename(self.jobs_dir / "queue" / job_id)
        done = self.jobs_dir / "done" / job_id
        deadline = time.monotonic() + timeout + GRACE_SECONDS
        while not (done / "result.json").is_file():
            if (self.jobs_dir / "queue" / job_id / runner.CANCEL).exists():
                # Cancelled before the runner took it: taken back if still queued.
                shutil.rmtree(self.jobs_dir / "queue" / job_id, ignore_errors=True)
                if (
                    not (self.jobs_dir / "queue" / job_id).exists()
                    and not (self.jobs_dir / "work" / job_id).exists()
                ):
                    return JobAnswer(status="cancelled")
            if time.monotonic() > deadline:
                # Never picked up, or the runner died with it: take it back if still queued.
                shutil.rmtree(self.jobs_dir / "queue" / job_id, ignore_errors=True)
                raise RunnerUnavailable(t("The Modelica runner did not answer in time."))
            time.sleep(self.poll_seconds)
        collected = self.jobs_dir / "collected" / job_id
        done.rename(collected)
        return _answer(collected)

    def cancel(self, job_id: str) -> None:
        """Ask the runner to stop the job (it kills omc); a queued job is taken back."""

        for folder in ("queue", "work"):
            target = self.jobs_dir / folder / job_id
            try:
                (target / runner.CANCEL).touch()
            except OSError:
                pass

    def output(self, job_id: str, name: str) -> Path | None:
        """A file the running job is writing (``res_3.csv``), to follow its progress."""

        path = self.jobs_dir / "work" / job_id / "out" / name
        return path if path.is_file() else None


class LocalExecutor:
    """The runner's code on this machine (development only: ``MODELCRAFT_RUNNER=local``)."""

    def __init__(self, jobs_dir: Path, *, omc: str = "omc", libraries: Path | None = None):
        self.jobs_dir = jobs_dir
        self.omc = omc
        self.libraries = libraries or Path(os.environ.get("MODELCRAFT_LIBRARIES", "/opt/modelica"))
        self.lock = threading.Semaphore(2)
        jobs_dir.mkdir(parents=True, exist_ok=True)
        self.version = runner.omc_version(omc)

    def state(self) -> dict[str, Any]:
        return {
            "available": bool(self.version),
            "reason": "" if self.version else t("omc is not installed on this machine."),
            "omc": self.version,
            "libraries": dict(runner.LIBRARY_VERSIONS),
            "workers": 2,
            "queued": 0,
            "running": 0,
        }

    def run(
        self,
        job: dict[str, Any],
        files: dict[str, str],
        *,
        timeout: float,
        extra: dict[str, bytes] | None = None,
        job_id: str | None = None,
    ) -> JobAnswer:
        if not self.version:
            raise RunnerUnavailable(t("omc is not installed on this machine."))
        folder = self.jobs_dir / (job_id or new_job_id())
        shutil.rmtree(folder, ignore_errors=True)
        _write_job(folder, {**job, "timeout": timeout}, files, extra or {})
        with self.lock:
            runner.execute(folder, omc=self.omc, libraries=self.libraries)
        return _answer(folder)

    def cancel(self, job_id: str) -> None:
        try:
            (self.jobs_dir / job_id / runner.CANCEL).touch()
        except OSError:
            pass

    def output(self, job_id: str, name: str) -> Path | None:
        path = self.jobs_dir / job_id / "out" / name
        return path if path.is_file() else None


class SuiteExecutor:
    """The runners on PlantCraft's compute workers (``MODELCRAFT_RUNNER=suite``, the default).

    Each job goes to PlantCraft as a compute task with this app's service token; a worker's
    gateway puts it in its runner's folder and sends the answer back, collected here into
    ``<jobs>/collected``. A run's progress is not followed while it runs on a worker (its
    partial results stay there): ``output`` has nothing.
    """

    def __init__(self, jobs_dir: Path, client: Callable[[], PlantCraftClient | None]):
        self.jobs_dir = jobs_dir
        self.client = client
        self.lock = threading.Lock()
        # Job id -> compute task id, while it runs (to cancel it).
        self.tasks: dict[str, str] = {}
        self.cancelled: set[str] = set()
        self._capacity: tuple[float, dict[str, Any]] | None = None
        (jobs_dir / "collected").mkdir(parents=True, exist_ok=True)

    def _compute(self) -> ComputeClient:
        client = self.client()
        if client is None:
            raise RunnerUnavailable(
                t(
                    "PlantCraft Models has no app key, so it cannot hand jobs to PlantCraft's "
                    "compute workers."
                )
            )
        return ComputeClient(client, version=SUITE_VERSION)

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._capacity is not None and now - self._capacity[0] < CAPACITY_SECONDS:
            return self._capacity[1]
        try:
            found = self._compute().capacity()
        except RunnerUnavailable as exc:
            state = {"available": False, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - PlantCraft restarting
            state = {
                "available": False,
                "reason": t("PlantCraft's compute did not answer: {error}", error=exc),
            }
        else:
            available = int(found.get("workers") or 0) > 0
            state = {
                "available": available,
                "reason": ""
                if available
                else t(
                    "No compute worker runs Modelica: add one in PlantCraft › Settings › Compute."
                ),
                "workers": found.get("slots"),
                "queued": int(found.get("queued") or 0),
                "running": int(found.get("running") or 0),
                # Where a run may go (docs/compute.md, "Environments and sizes").
                "environments": list(found.get("environments") or []),
                "sizes": list(found.get("sizes") or []),
            }
        self._capacity = (now, state)
        return state

    def run(
        self,
        job: dict[str, Any],
        files: dict[str, str],
        *,
        timeout: float,
        extra: dict[str, bytes] | None = None,
        job_id: str | None = None,
    ) -> JobAnswer:
        state = self.state()
        if not state["available"]:
            raise RunnerUnavailable(state["reason"])
        compute = self._compute()
        job_id = job_id or new_job_id()
        # Where it may run: a worker with this environment and room for this size.
        job = dict(job)
        placement = job.pop("compute", None) or {}
        folder: dict[str, bytes | str] = {
            "job.json": json.dumps({**job, "id": job_id, "timeout": timeout}),
            **{f"files/{path}": text for path, text in files.items()},
            **(extra or {}),
        }
        try:
            task_id = compute.submit(
                folder,
                kind=str(job.get("kind") or "job"),
                run=job_id,
                timeout_seconds=timeout + 60,
                environment=placement.get("environment"),
                size=placement.get("size"),
            )
        except Exception as exc:  # noqa: BLE001 - not run: the caller says why
            raise RunnerUnavailable(
                t("PlantCraft's compute queue did not take the job: {error}", error=exc)
            )
        with self.lock:
            self.tasks[job_id] = task_id
            cancelled = job_id in self.cancelled
        try:
            if cancelled:
                compute.cancel(task_id)
            answer = next(
                compute.answers([task_id], timeout=timeout + GRACE_SECONDS + QUEUE_SECONDS)
            )
        finally:
            with self.lock:
                self.tasks.pop(job_id, None)
                cancelled = job_id in self.cancelled
                self.cancelled.discard(job_id)
        if answer.status == "cancelled":
            if cancelled:
                return JobAnswer(status="cancelled")
            raise RunnerUnavailable(
                t(
                    "No Modelica runner answered in time: {error}",
                    error=answer.error or "cancelled",
                )
            )
        if answer.status != "done":
            return JobAnswer(status="error", error=answer.error or t("The compute task failed."))
        collected = self.jobs_dir / "collected" / job_id
        shutil.rmtree(collected, ignore_errors=True)
        (collected / "out").mkdir(parents=True)
        write_json(collected / "result.json", answer.result)
        for name, content in answer.files.items():
            target = (collected / "out" / name).resolve()
            if collected / "out" in target.parents:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        return _answer(collected)

    def cancel(self, job_id: str) -> None:
        with self.lock:
            self.cancelled.add(job_id)
            task_id = self.tasks.get(job_id)
        if task_id is not None:
            try:
                self._compute().cancel(task_id)
            except Exception:  # noqa: BLE001, S110 - the run's own time limit still applies
                pass

    def output(self, job_id: str, name: str) -> Path | None:
        return None
