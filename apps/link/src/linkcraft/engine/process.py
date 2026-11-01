"""The engine in a process of its own (``LINKCRAFT_ENGINE``).

- ``process`` (the default): ``linkcraft serve`` starts ``linkcraft engine`` as its child and
  starts it again if it stops. The pages never share a processor with a long round.
- ``external``: nothing is started; ``linkcraft engine`` runs elsewhere (its own container).
- ``inline``: the engine runs in the server's own process (the tests, a laptop).

One engine per database: the engine holds a lease (an exclusive ``flock`` on a file beside the
database, released by the kernel when its process ends), and a second one waits as a standby,
taking over within seconds once the first one stops. A child engine also stops when the server
that started it is gone.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plantcraft_sdk.server.lease import FileLease
from plantcraft_sdk.server.memory import Releaser

LOGGER = logging.getLogger(__name__)
# A standby engine asks for the lease this often; a child looks for its server this often.
LEASE_SECONDS = 5.0
PARENT_SECONDS = 2.0
# A child that stopped is started again after this long, doubling up to the last value.
RESTART_SECONDS = (1.0, 60.0)
STEADY_SECONDS = 60.0
# This many restarts within the window make the server unhealthy (a crash loop, most often the
# container's memory limit: the server stays up while its engine dies again and again).
CRASH_LOOP_RESTARTS = 3
CRASH_LOOP_SECONDS = 600.0


def lease_for(database: Path) -> FileLease:
    return FileLease(database.with_name(database.name + ".engine.lock"))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_engine(
    settings: Any,
    runtime_of: Callable[[Any], Any],
    *,
    parent: int | None = None,
    stop: threading.Event | None = None,
) -> int:
    """Run the engine of ``runtime_of(settings)`` here until stopped (``SIGTERM``, ``stop``, or
    ``parent`` gone)."""

    stop = stop or threading.Event()
    if threading.current_thread() is threading.main_thread():
        for name in ("SIGTERM", "SIGINT"):
            signal.signal(getattr(signal, name), lambda *_: stop.set())

    def wanted() -> bool:
        return not stop.is_set() and (parent is None or _alive(parent))

    lease = lease_for(settings.database_path)
    waiting = False
    while wanted() and not lease.acquire():
        if not waiting:
            LOGGER.info("Another engine runs on this database: this one waits as a standby")
            waiting = True
        stop.wait(LEASE_SECONDS)
    if not wanted():
        lease.release()
        return 0
    settings.engine = "inline"
    runtime = runtime_of(settings)
    # What rounds and executions freed goes back to the system (plantcraft_sdk.server.memory).
    releaser = Releaser().start()
    try:
        runtime.start_engine()
        LOGGER.info("Analytics engine started (%d workers)", runtime.engine.dispatcher.slots)
        while wanted():
            stop.wait(PARENT_SECONDS)
    finally:
        LOGGER.info("Analytics engine stopping")
        releaser.stop()
        runtime.shutdown()
        lease.release()
    return 0


class EngineProcess:
    """``linkcraft engine`` as a child of the server, started again whenever it stops."""

    def __init__(self, settings: Any, command: list[str] | None = None):
        self.settings = settings
        self.command = command or [
            sys.executable,
            "-m",
            "linkcraft.cli",
            "engine",
            "--parent",
            str(os.getpid()),
        ]
        self.process: subprocess.Popen[bytes] | None = None
        self.restarts = 0
        self._restarted_at: list[float] = []
        self._started_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def crash_loop(self, now: float | None = None) -> str | None:
        """What is wrong when the engine was started again ``CRASH_LOOP_RESTARTS`` times within
        ``CRASH_LOOP_SECONDS``; ``None`` otherwise."""

        now = time.monotonic() if now is None else now
        recent = [t for t in self._restarted_at if now - t <= CRASH_LOOP_SECONDS]
        if len(recent) < CRASH_LOOP_RESTARTS:
            return None
        return (
            f"The engine process stopped {len(recent)} times in the last "
            f"{int(CRASH_LOOP_SECONDS // 60)} minutes (often the memory limit, LINKCRAFT_MEMORY)."
        )

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._spawn()
        self._thread = threading.Thread(target=self._watch, name="engine-watch", daemon=True)
        self._thread.start()

    def _spawn(self) -> None:
        self.process = subprocess.Popen(self.command, env=os.environ.copy())
        self._started_at = time.monotonic()
        LOGGER.info("Analytics engine process %d started", self.process.pid)

    def _watch(self) -> None:
        delay = RESTART_SECONDS[0]
        while not self._stop.wait(PARENT_SECONDS):
            if self.alive:
                # One that ran a while gets the short wait again the next time it stops.
                if time.monotonic() - self._started_at > STEADY_SECONDS:
                    delay = RESTART_SECONDS[0]
                continue
            code = self.process.returncode if self.process is not None else None
            LOGGER.warning(
                "The engine process stopped (exit %s): started again in %.0f s", code, delay
            )
            if self._stop.wait(delay):
                return
            self._spawn()
            self.restarts += 1
            self._restarted_at.append(time.monotonic())
            del self._restarted_at[:-CRASH_LOOP_RESTARTS]
            delay = min(RESTART_SECONDS[1], delay * 2)

    def stop(self, timeout: float = 20.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
