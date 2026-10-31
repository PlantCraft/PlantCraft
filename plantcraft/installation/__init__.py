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


# What the installation file (/etc/plantcraft/installation.conf, docs/installation-file.md)
# decided, as install.sh lists it in PLANTCRAFT_INSTALLATION_LOCKED: shown read-only in
# Settings › Installation, changed only on the server (edit the file, run install.sh again).
LOCKED_LABELS: dict[str, str] = {
    "COMPOSE_PROFILES": "Apps installed",
    "PLANTCRAFT_APP_INSTALL": "Install apps from Settings › Apps",
    "PLANTCRAFT_LLM": "Language models",
    "PLANTCRAFT_MCP": "Assistants from outside (MCP)",
    "PLANTCRAFT_NOTEBOOKS": "Notebooks",
    "PLANTCRAFT_MACHINE": "Machine size",
    "PLANTCRAFT_MAX_CPUS": "Most CPUs for the suite",
    "PLANTCRAFT_MAX_MEMORY": "Most memory for the suite",
    "PLANTCRAFT_MAX_SIGNALS": "Signals the Historian may record",
    "PLANTCRAFT_MAX_PARALLEL_RUNS": "Analysis runs at once",
    "PLANTCRAFT_MAX_SESSIONS": "People signed in at once",
    "PLANTCRAFT_HOSTNAME": "Server names",
    "PLANTCRAFT_HTTPS_PORT": "HTTPS port",
    "PLANTCRAFT_BIND_ADDRESS": "Listen on",
    "PLANTCRAFT_PLANT_SUBNET": "Internal networks",
    "PLANTCRAFT_TIMEZONE": "Time zone",
    "PLANTCRAFT_TIMEZONE_LOCKED": "Time zone locked",
}
# Keys shown as one line (the seven subnets as "Internal networks"), or not at all.
FOLDED = {
    "PLANTCRAFT_APPS_SUBNET",
    "PLANTCRAFT_EDGE_SUBNET",
    "PLANTCRAFT_DEMO_SUBNET",
    "PLANTCRAFT_HISTDB_SUBNET",
    "PLANTCRAFT_LLM_SUBNET",
    "PLANTCRAFT_EGRESS_SUBNET",
    "PLANTCRAFT_PROXY_ADDRESS",
}


def installation_file() -> dict[str, Any]:
    """What the installation file decided (empty ``entries`` when there is none): each key's
    label and the value this process runs with, and the file's SHA-256 as install.sh saw it."""

    keys = [
        key.strip()
        for key in (os.environ.get("PLANTCRAFT_INSTALLATION_LOCKED") or "").split(",")
        if key.strip()
    ]
    entries = []
    for key in keys:
        if key in FOLDED:
            continue
        value = os.environ.get(key, "")
        if key == "COMPOSE_PROFILES":
            value = ",".join(
                part.split("=", 1)[0]
                for part in (os.environ.get("PLANTCRAFT_APPS") or "").split(",")
                if part.strip()
            )
        if key == "PLANTCRAFT_PLANT_SUBNET":
            value = f"{value} … {os.environ.get('PLANTCRAFT_EGRESS_SUBNET', '')}"
        entries.append({"key": key, "label": LOCKED_LABELS.get(key, key), "value": value})
    sha = (os.environ.get("PLANTCRAFT_INSTALLATION_CONF_SHA256") or "").strip().lower()
    return {
        "present": bool(keys),
        "path": "/etc/plantcraft/installation.conf",
        "sha256": sha if re.fullmatch(r"[0-9a-f]{64}", sha) else None,
        "entries": entries,
    }


def zone_locked() -> bool:
    """True when the installation file fixed the time zone (``LOCK_TIMEZONE=yes``): then the
    zone install.sh wrote wins and Settings › Installation cannot change it."""

    return (os.environ.get("PLANTCRAFT_TIMEZONE_LOCKED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        if zone_locked():
            return None
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
            "locked": zone_locked(),
            "installation_file": installation_file(),
            "updated_by": stored.get("updated_by"),
            "updated_at": stored.get("updated_at"),
        }

    def save_time_zone(self, zone: str, *, actor: str) -> dict[str, Any]:
        """Saves an IANA zone; raises ValueError for one this server does not know."""

        if zone_locked():
            raise PermissionError("the installation file fixed the time zone")
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
