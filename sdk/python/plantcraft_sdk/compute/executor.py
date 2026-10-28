"""An app's executor: runs the tasks of one app that a worker's gateway puts in its folder.

The executor is the sandbox of the suite's compute (docs/compute.md): its container has no
network at all, no secret, a read-only image and limits on CPU, memory and processes. It shares
only its job folder with the gateway (``plantcraft_sdk.compute.folder``). Each task runs in a
child process of its own slot, which the executor stops when the task takes longer than its
``timeout_seconds`` or is cancelled, and starts again for the next task; a task that uses more
than its memory fails alone (``MemoryError``). The child also refuses sockets and files bigger
than an answer may be.

The app gives the work as ``handler``, a ``"module:function"`` name, so the child imports it
once: ``handler(job_dir)`` reads ``job.json`` and its files and writes ``result.json`` and the
files under ``out/``. A handler that raises gives ``{"status": "error", "error": ...}``::

    python -m plantcraft_sdk.compute executor --app linkcraft --version 0.5.0 \\
        --jobs /jobs --handler linkcraft.compute:answer --workers 4

``--environment`` names an image with more than the app's own packages (``standard`` by
default): it takes only the tasks that ask for it, from ``<jobs>/<app>.<environment>/``.
``--memory-mb`` is the most memory each task may use.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import shutil
import signal
import threading
import time
import traceback
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from plantcraft_sdk.compute import folder

LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MEMORY_MB = 2048
POLL_SECONDS = 0.05
HEARTBEAT_SECONDS = 10.0


def _child_limits(memory_mb: int, max_file_bytes: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_bytes, max_file_bytes))
        if memory_mb > 0:
            used = 0
            try:
                with open("/proc/self/status", encoding="ascii") as status:
                    for line in status:
                        if line.startswith("VmSize:"):
                            used = int(line.split()[1]) * 1024
            except OSError:
                used = 0
            if used:
                limit = used + memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # not Linux: the timeout still applies
        LOGGER.info("Executor children run without resource limits on this system.")
    import socket

    def refused(*_args: Any, **_kwargs: Any) -> Any:  # noqa: ANN401
        raise OSError("A task has no network access.")

    class NoNetwork(socket.socket):
        """Still a class: a module imported later subclasses it (``ssl.SSLSocket``, which
        ``httpx`` brings in) and only opening one is refused."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: ANN401
            refused()

    socket.socket = NoNetwork  # type: ignore[assignment,misc]
    socket.create_connection = refused  # type: ignore[assignment]
    socket.getaddrinfo = refused  # type: ignore[assignment]


def _resolve(handler: str) -> Any:  # noqa: ANN401
    module_name, _, function = handler.partition(":")
    module = __import__(module_name, fromlist=[function or "answer"])
    return getattr(module, function or "answer")


def _child(connection: Connection, handler: str, memory_mb: int, max_file_bytes: int) -> None:
    """A slot's process: imports the handler once, then answers the job folders it is sent."""

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    function = _resolve(handler)
    _child_limits(memory_mb, max_file_bytes)
    connection.send("ready")
    while True:
        try:
            job = connection.recv()
        except EOFError:
            return
        if job is None:
            return
        job_dir = Path(job)
        try:
            function(job_dir)
            if not (job_dir / folder.RESULT).exists():
                folder.write_json(job_dir / folder.RESULT, {"status": "done"})
        except MemoryError:
            _error(job_dir, "the task used more memory than it may")
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            _error(job_dir, f"{type(exc).__name__}: {exc}", traceback.format_exc(limit=6))
        connection.send("answered")


def _error(job_dir: Path, text: str, trace: str = "") -> None:
    shutil.rmtree(job_dir / folder.OUT, ignore_errors=True)
    folder.write_json(
        job_dir / folder.RESULT, {"status": "error", "error": text[:2000], "trace": trace[-4000:]}
    )


class _Slot:
    """One child process, started again after a task it had to stop."""

    def __init__(self, handler: str, memory_mb: int, max_file_bytes: int):
        self.handler = handler
        self.memory_mb = memory_mb
        self.max_file_bytes = max_file_bytes
        self.process: Any = None
        self.connection: Connection | None = None

    def start(self) -> None:
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self.process = context.Process(
            target=_child,
            args=(child, self.handler, self.memory_mb, self.max_file_bytes),
            daemon=True,
        )
        self.process.start()
        child.close()
        self.connection = parent
        if not parent.poll(120) or parent.recv() != "ready":
            self.stop()
            raise RuntimeError(f"the executor's process could not start {self.handler}")

    def stop(self) -> None:
        if self.process is not None and self.process.is_alive():
            self.process.kill()
            self.process.join(5)
        self.process = None
        self.connection = None

    def run(self, job_dir: Path, timeout: float) -> str:
        """``answered``, ``timeout``, ``cancelled`` or ``died``."""

        if self.process is None or not self.process.is_alive():
            self.start()
        assert self.connection is not None
        self.connection.send(str(job_dir))
        deadline = time.monotonic() + timeout
        while True:
            if self.connection.poll(POLL_SECONDS):
                try:
                    return "answered" if self.connection.recv() == "answered" else "died"
                except EOFError:
                    self.stop()
                    return "died"
            if not self.process.is_alive():
                self.stop()
                return "died"
            if (job_dir / folder.CANCEL).exists():
                self.stop()
                return "cancelled"
            if time.monotonic() > deadline:
                self.stop()
                return "timeout"


class Executor:
    def __init__(
        self,
        jobs: Path,
        *,
        app: str,
        version: str | None,
        handler: str,
        environment: str = folder.DEFAULT_ENVIRONMENT,
        workers: int = 1,
        memory_mb: int = DEFAULT_MEMORY_MB,
        max_file_bytes: int = folder.DEFAULT_MAX_BYTES,
    ):
        self.jobs = jobs
        self.app = app
        self.version = version
        self.environment = folder.environment_name(environment) or folder.DEFAULT_ENVIRONMENT
        self.handler = handler
        self.workers = max(1, workers)
        self.memory_mb = memory_mb
        self.max_file_bytes = max_file_bytes
        self.stop = threading.Event()
        folder.prepare(jobs)

    def heartbeat(self) -> None:
        folder.write_json(
            self.jobs / folder.HEARTBEAT,
            {
                "app": self.app,
                "environment": self.environment,
                "version": self.version,
                "workers": self.workers,
                "memory_mb": self.memory_mb,
                "protocol": folder.PROTOCOL,
                "at": time.time(),
            },
        )

    def claim(self) -> Path | None:
        try:
            entries = sorted((self.jobs / folder.QUEUE).iterdir(), key=lambda path: path.name)
        except OSError:
            return None
        for entry in entries:
            if entry.name.startswith("."):
                continue
            target = self.jobs / folder.WORK / entry.name
            try:
                entry.rename(target)
            except OSError:
                continue  # another slot took it
            return target
        return None

    def answer(self, slot: _Slot, job_dir: Path) -> None:
        task = folder.read_json(job_dir / folder.TASK) or {}
        try:
            timeout = float(task.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_SECONDS
        started = time.monotonic()
        try:
            outcome = slot.run(job_dir, timeout)
        except Exception as exc:  # noqa: BLE001 - a job never stops the executor
            slot.stop()
            outcome = "died"
            LOGGER.exception("executor: %s", exc)
        seconds = round(time.monotonic() - started, 3)
        if outcome == "timeout":
            _error(job_dir, f"the task took longer than its {timeout:g} s")
        elif outcome == "cancelled":
            folder.write_json(job_dir / folder.RESULT, {"status": "cancelled"})
        elif outcome == "died":
            _error(job_dir, "the task's process stopped (it used too much memory, or crashed)")
        result = folder.read_json(job_dir / folder.RESULT) or {"status": "error"}
        result.setdefault("seconds", seconds)
        folder.write_json(job_dir / folder.RESULT, result)
        target = self.jobs / folder.DONE / job_dir.name
        shutil.rmtree(target, ignore_errors=True)
        job_dir.rename(target)

    def work(self) -> None:
        slot = _Slot(self.handler, self.memory_mb, self.max_file_bytes)
        try:
            while not self.stop.is_set():
                job_dir = self.claim()
                if job_dir is None:
                    self.stop.wait(POLL_SECONDS * 2)
                    continue
                self.answer(slot, job_dir)
        finally:
            slot.stop()

    def clean(self, older_than: float = 3600) -> None:
        """Answers the gateway never took (it restarted) go after an hour."""

        limit = time.time() - older_than
        for entry in (self.jobs / folder.DONE).iterdir():
            try:
                if entry.stat().st_mtime < limit:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                pass

    def serve(self) -> None:
        # Tasks a previous executor left half done are run again.
        for entry in (self.jobs / folder.WORK).iterdir():
            try:
                entry.rename(self.jobs / folder.QUEUE / entry.name)
            except OSError:
                pass
        self.heartbeat()
        threads = [
            threading.Thread(target=self.work, name=f"slot-{index}", daemon=True)
            for index in range(self.workers)
        ]
        for thread in threads:
            thread.start()
        while not self.stop.wait(HEARTBEAT_SECONDS):
            self.heartbeat()
            self.clean()
        for thread in threads:
            thread.join(10)


__all__ = ["Executor"]
