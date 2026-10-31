"""Several server processes on one installation (``PLANTCRAFT_WORKERS``, docs/operations.md).

PlantCraft answers from 2 to 4 processes when HistCraft is the data layer: one Python process
holds one request in Python code at a time (the GIL), so many people at once wait in line.
Everything they share lives in the data folder: the database (WAL, ``plantcraft.db``), the
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
from pathlib import Path

from plantcraft_sdk.server.store import journal_mode

# The locks between processes are the SDK's (every app that runs several processes shares them).
from plantcraft_sdk.server.workers import (  # noqa: F401
    LEADER_RETRY_SECONDS,
    MAX_WORKERS,
    Leader,
    available_cpus,
    first_only,
    startup,
)

LOGGER = logging.getLogger(__name__)


def worker_count(
    environ: dict[str, str] | None = None,
    cpus: int | None = None,
    folder: str | Path | None = None,
) -> int:
    """How many server processes to start.

    ``PLANTCRAFT_WORKERS`` is a number (1 to 8) or ``auto`` (the default): 1 while PlantCraft
    reads plant sources itself (its history cache lives in the process), else the container's
    CPUs (its cgroup quota, not the host's cores: ``available_cpus``) up to 4, at least 2.

    Always 1 when the database's ``folder`` is where SQLite cannot use WAL (a Docker Desktop
    bind mount, a share, FUSE: ``plantcraft_sdk.server.store.journal_mode``): file locks there do
    not hold between processes, and several writers corrupted a new database (macOS install
    test, 0.5.1).
    """

    environ = os.environ if environ is None else environ
    if folder is not None and journal_mode(Path(folder)) != "WAL":
        return 1
    value = (environ.get("PLANTCRAFT_WORKERS") or "auto").strip().lower()
    if value != "auto":
        try:
            return max(1, min(MAX_WORKERS, int(value)))
        except ValueError:
            LOGGER.warning("PLANTCRAFT_WORKERS=%r is not a number: using auto", value)
    if not (environ.get("HISTCRAFT_URL") or "").strip():
        return 1
    return max(2, min(4, cpus if cpus is not None else available_cpus()))
