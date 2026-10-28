"""One process at a time on a file: the lease a writer holds (an app's engine, a collector).

An exclusive ``flock`` on a lock file, released by the kernel when the process ends, so a second
process waits as a standby and takes over within seconds once the first one stops. On a system
without ``fcntl`` (Windows) the lease is always granted: a Windows install runs one process.
Standard library only.
"""

from __future__ import annotations

import os
from pathlib import Path


class FileLease:
    """Taken with ``acquire`` (never blocks), checked with ``alive``, given up with ``release``."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        try:
            import fcntl
        except ImportError:  # Windows: one process
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o660)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return True

    def alive(self) -> bool:
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            import fcntl

            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None
