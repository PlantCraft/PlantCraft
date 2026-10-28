"""One collector per archive: the lease a collector holds while it writes.

Two collectors on one archive would each write their own chunks for the same points (an
embedded one left on beside the ``histcraft-collector`` container, two containers after a
mistaken scale, an update that starts the new one before the old one stopped). The lease
makes the second one wait instead: it takes over within seconds once the first one stops.

- PostgreSQL: a session advisory lock, held by one connection of its own. The server
  releases it when that connection ends, also when the collector's process dies.
- SQLite: an exclusive ``flock`` on a file beside the archive, released by the kernel when
  the process ends. On a system without ``fcntl`` (Windows) the lease is always granted:
  a Windows install runs one ``histcraft serve`` with its collector embedded.
"""

from __future__ import annotations

import logging
from typing import Any

from plantcraft_sdk.server.lease import FileLease as _FileLease

from histcraft.db import Database

LOGGER = logging.getLogger(__name__)
# pg_try_advisory_lock(LEASE_KEY, hashtext(current_schema())): one lease per archive schema.
LEASE_KEY = 420710


class Lease:
    """Taken with ``acquire`` (never blocks), checked with ``alive``, given up with ``release``."""

    def acquire(self) -> bool:
        raise NotImplementedError

    def alive(self) -> bool:
        return True

    def release(self) -> None:
        return None


class FileLease(_FileLease, Lease):
    """The SQLite archive's lease: ``plantcraft_sdk.server.lease.FileLease``."""


class PostgresLease(Lease):
    def __init__(self, archive: Database):
        self.archive = archive
        self._connection: Any = None

    def acquire(self) -> bool:
        if self._connection is not None:
            return self.alive()
        connection = self.archive.own_connection()
        try:
            granted = connection.execute(
                "SELECT pg_try_advisory_lock(%s, hashtext(current_schema()))", (LEASE_KEY,)
            ).fetchone()[0]
        except Exception:
            connection.close()
            raise
        if not granted:
            connection.close()
            return False
        self._connection = connection
        return True

    def alive(self) -> bool:
        """False once the lease's connection is gone (the server released the lock)."""

        if self._connection is None:
            return False
        try:
            self._connection.execute("SELECT 1").fetchone()
            return True
        except Exception:  # noqa: BLE001 - any failure means the lock may be someone else's
            self.release()
            return False

    def release(self) -> None:
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.close()  # ends the session: the server drops its advisory locks
        except Exception:  # noqa: BLE001
            LOGGER.debug("Closing the lease connection failed", exc_info=True)


def lease_for(archive: Database) -> Lease:
    """The lease of the archive in ``archive`` (its database or its file)."""

    if archive.postgres:
        return PostgresLease(archive)
    assert archive.path is not None
    return FileLease(archive.path.with_name(archive.path.name + ".collector.lock"))
