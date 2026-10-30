"""The installation's own settings, set once in Settings › Installation: for now its time zone,
and its id.

The id names this installation among a company's others (one per plant or site): it goes into
API v1 (``GET /api/v1/installation``), exports and backups, so data from several plants can be
told apart and put together later. ``install.sh`` writes it once into
``PLANTCRAFT_INSTALLATION_ID``; without that (a source checkout, a test) the database keeps
one made on first use. It never changes.

The time zone is where the plant's days, shifts and "today" begin, and the "Local time" every
screen shows by default. ``install.sh`` writes the server's zone into
``PLANTCRAFT_TIMEZONE``; that is only the starting value: what an administrator saves here
wins. Stored times stay UTC (``plantcraft.db.utc_text``).
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any

from plantcraft.config import plant_timezone, use_installation_zone, valid_zone
from plantcraft.db import Database, Store

INSTALLATION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def installed_id() -> str | None:
    """The id ``install.sh`` wrote (``PLANTCRAFT_INSTALLATION_ID``), None when missing or wrong."""

    value = (os.environ.get("PLANTCRAFT_INSTALLATION_ID") or "").strip().lower()
    return value if INSTALLATION_ID.match(value) else None


def installed_zone() -> str:
    """The zone ``install.sh`` wrote (``PLANTCRAFT_TIMEZONE``), UTC when it is missing or wrong."""

    name = (os.environ.get("PLANTCRAFT_TIMEZONE") or "").strip()
    return name if name and valid_zone(name) else "UTC"


class InstallationStore(Store):
    """One row: the time zone an administrator chose (none until they do)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS installation_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        time_zone TEXT,
        updated_by TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS installation_identity (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        installation_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """

    def __init__(self, db: Database):
        super().__init__(db)
        # plant_timezone() everywhere in this process reads the saved zone first.
        use_installation_zone(self.saved_zone)

    def installation_id(self) -> str:
        """This installation's id: ``PLANTCRAFT_INSTALLATION_ID``, else the one kept here
        (made on first use)."""

        found = installed_id()
        if found:
            return found
        with self._lock, self._write() as connection:
            # OR IGNORE: another server process may have made it first; its id wins.
            connection.execute(
                "INSERT OR IGNORE INTO installation_identity (id, installation_id, created_at)"
                " VALUES (1, ?, ?)",
                (str(uuid.uuid4()), self._now()),
            )
            row = connection.execute(
                "SELECT installation_id FROM installation_identity WHERE id = 1"
            ).fetchone()
        return str(row["installation_id"])

    def saved_zone(self) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT time_zone FROM installation_settings WHERE id = 1"
            ).fetchone()
        zone = (row["time_zone"] or "").strip() if row else ""
        return zone if zone and valid_zone(zone) else None

    def settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM installation_settings WHERE id = 1").fetchone()
        stored = dict(row) if row else {}
        return {
            "id": self.installation_id(),
            "time_zone": plant_timezone(fresh=True).key,
            "installed_time_zone": installed_zone(),
            "chosen": bool(self.saved_zone()),
            "updated_by": stored.get("updated_by"),
            "updated_at": stored.get("updated_at"),
        }

    def save_time_zone(self, zone: str, *, actor: str) -> dict[str, Any]:
        """Saves an IANA zone; raises ValueError for one this server does not know."""

        zone = zone.strip()
        if not valid_zone(zone):
            raise ValueError(zone)
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO installation_settings (id, time_zone, updated_by, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET time_zone = excluded.time_zone,
                    updated_by = excluded.updated_by, updated_at = excluded.updated_at
                """,
                (zone, actor, self._now()),
            )
        return self.settings()
