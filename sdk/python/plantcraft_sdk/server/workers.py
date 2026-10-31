"""Several server processes for one app: how many, one start at a time, one leader.

One Python process holds one request in Python code at a time (the GIL), so an app that answers
heavy reads (the Historian under Analytics' rounds, 0.6.0 load tests) or many people at once
waits in line on one core. An app runs in several processes when everything they share lives in
its database or its data folder; three things then need a word between the processes:

- ``worker_count``: how many processes, from the app's ``<APP>_WORKERS`` setting (a number or
  ``auto``), the CPUs the container may use (``available_cpus``, the cgroup limit, not the
  host's count), and always 1 where SQLite cannot use WAL (file locks do not hold between
  processes there: a Docker Desktop bind mount, a share, FUSE).
- ``startup``: the processes start together; one at a time opens the database and fills in what
  a first start writes (schemas, starter rows).
- ``Leader``: the duties that must run once per installation (a sampler, an outbox) run in the
  one process holding the leader file; another takes over within seconds when that one ends.

Locks are ``flock`` on files in the data folder, released by the kernel when a process dies.
Without ``fcntl`` (Windows) there is one process, and every lock is granted.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from plantcraft_sdk.server.store import journal_mode

LOGGER = logging.getLogger(__name__)
MAX_WORKERS = 8
# A process waiting to lead asks again this often.
LEADER_RETRY_SECONDS = 5.0

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


def available_cpus(root: str | Path = "/sys/fs/cgroup") -> int:
    """The CPUs this process may use: the container's limit (cgroup v2 ``cpu.max`` or v1
    ``cpu.cfs_quota_us``), rounded up, else the CPUs it may run on."""

    root = Path(root)
    try:
        quota, period = (root / "cpu.max").read_text().split()[:2]
        if quota != "max":
            return max(1, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError):
        try:
            quota = int((root / "cpu" / "cpu.cfs_quota_us").read_text())
            period = int((root / "cpu" / "cpu.cfs_period_us").read_text())
            if quota > 0 and period > 0:
                return max(1, math.ceil(quota / period))
        except (OSError, ValueError):
            pass
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def worker_count(
    setting: str,
    environ: Mapping[str, str] | None = None,
    *,
    auto: int | None = None,
    folder: str | Path | None = None,
) -> int:
    """How many server processes to start, from ``environ[setting]``: a number (1 to 8) or
    ``auto`` (the default), which is ``auto`` when given, else the available CPUs up to 4.

    Always 1 when SQLite in ``folder`` cannot use WAL, and without ``fcntl``.
    """

    environ = os.environ if environ is None else environ
    if fcntl is None or (folder is not None and journal_mode(Path(folder)) != "WAL"):
        return 1
    value = (environ.get(setting) or "auto").strip().lower()
    if value != "auto":
        try:
            return max(1, min(MAX_WORKERS, int(value)))
        except ValueError:
            LOGGER.warning("%s=%r is not a number: using auto", setting, value)
    return max(1, min(MAX_WORKERS, auto if auto is not None else min(4, available_cpus())))


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
