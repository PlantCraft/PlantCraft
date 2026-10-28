"""Several server processes on one installation (``PLANTCRAFT_WORKERS``, docs/operations.md).

PlantCraft answers from 2 to 4 processes when HistCraft is the data layer: one Python process
holds one request in Python code at a time (the GIL), so many people at once wait in line.
Everything they share lives in the data folder: the database (WAL, ``processcraft.db``), the
session and token keys (created once, ``O_EXCL``) and the login throttle (a table). Two things
need a word between the processes, both kept here:

- ``startup``: the processes start together; one at a time opens the database and fills in what
  a first start writes (schemas, starter types, the administrator).
- ``Leader``: the duties that must run once per installation (the suite's watch, the email
  outbox) run in the one process holding the leader file; another takes over within seconds when
  that process ends.

Locks are ``flock`` on files beside the database, released by the kernel when a process dies.
Without ``fcntl`` (Windows) there is one process, and every lock is granted.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOGGER = logging.getLogger(__name__)
MAX_WORKERS = 8
# A process waiting to lead asks again this often.
LEADER_RETRY_SECONDS = 5.0

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


def worker_count(environ: dict[str, str] | None = None, cpus: int | None = None) -> int:
    """How many server processes to start.

    ``PLANTCRAFT_WORKERS`` is a number (1 to 8) or ``auto`` (the default): 1 while PlantCraft
    reads plant sources itself (its history cache lives in the process), else the CPUs up to 4,
    at least 2.
    """

    environ = os.environ if environ is None else environ
    value = (environ.get("PLANTCRAFT_WORKERS") or "auto").strip().lower()
    if value != "auto":
        try:
            return max(1, min(MAX_WORKERS, int(value)))
        except ValueError:
            LOGGER.warning("PLANTCRAFT_WORKERS=%r is not a number: using auto", value)
    if not (environ.get("HISTCRAFT_URL") or "").strip():
        return 1
    return max(2, min(4, cpus if cpus is not None else os.cpu_count() or 1))


@contextmanager
def startup(folder: str | Path) -> Iterator[None]:
    """Hold the installation's start lock: one process at a time builds its runtime."""

    if fcntl is None:
        yield
        return
    path = Path(folder) / "startup.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing releases the lock


@contextmanager
def first_only(path: str | Path) -> Iterator[bool]:
    """True for the one process that holds ``path`` now, False for the others (never blocks):
    for work two processes must not do at once and the next round redoes anyway."""

    if fcntl is None:
        yield True
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


class Leader:
    """The process that runs the installation's once-only duties (``acquire`` never blocks)."""

    def __init__(self, folder: str | Path):
        self.path = Path(folder) / "leader.lock"
        self._fd: int | None = None
        self._lock = threading.Lock()

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        with self._lock:
            if self._fd is not None:
                return True
            if fcntl is None:
                self._fd = -1
                return True
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                return False
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
            self._fd = fd
            return True

    def release(self) -> None:
        with self._lock:
            fd, self._fd = self._fd, None
        if fd is not None and fd >= 0:
            os.close(fd)

    def wait(self, stop: threading.Event) -> bool:
        """Block until this process leads (True) or ``stop`` is set (False)."""

        announced = False
        while not stop.is_set():
            if self.acquire():
                if announced:
                    LOGGER.info("This process now runs the installation's background duties")
                return True
            if not announced:
                LOGGER.info("Another process runs the background duties; this one stands by")
                announced = True
            stop.wait(LEADER_RETRY_SECONDS)
        return False
