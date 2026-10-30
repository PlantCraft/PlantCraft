"""Folders of dashboards and who may see and change them (Grafana's folders, one level).

A folder names who sees its dashboards (``viewers``) and who changes them (``editors``), as
people (``user:<username>``) and groups of the platform (``group:<id>``). An empty list means
everyone: everyone with access to View sees, every View editor edits. Editors of a folder always
see it, administrators see and change every folder, and only View editors ever change anything.
Dashboards outside any folder (``folder_id`` ``""``, shown as "General") are everyone's, so
"General" is never a folder's name (``RESERVED``): a folder named so before 2026-10-26 showed a
second General; its step in ``MIGRATIONS`` files an open one's dashboards and reports in General
and renames one kept for some people.

Groups live in PlantCraft (``GET /api/v1/groups``); View keeps only their ids.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections.abc import Iterable
from typing import Any

from plantcraft_sdk.server.store import Migration, Store
from pydantic import BaseModel, Field, field_validator

from dashcraft.i18n import t

GENERAL = ""
MAX_FOLDERS = 200
MAX_ENTRIES = 100
# The name of what lies outside every folder: no folder takes it.
RESERVED = "general"
ENTRY = re.compile(r"^(user|group):[A-Za-z0-9_.@-]{1,80}$")


class FolderPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    viewers: list[str] = Field(default_factory=list, max_length=MAX_ENTRIES)
    editors: list[str] = Field(default_factory=list, max_length=MAX_ENTRIES)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("The name is required."))
        if value.casefold() == RESERVED:
            raise ValueError(
                t("General holds what is outside every folder: give the folder another name.")
            )
        return value

    @field_validator("viewers", "editors")
    @classmethod
    def _entries(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = (value or "").strip()
            if not ENTRY.match(value):
                raise ValueError(t("Name people as user:<username> and groups as group:<id>."))
            if value not in cleaned:
                cleaned.append(value)
        return cleaned


def _matches(entries: Iterable[str], username: str, groups: set[str]) -> bool:
    for entry in entries:
        kind, _, name = entry.partition(":")
        if (kind == "user" and name == username) or (kind == "group" and name in groups):
            return True
    return False


def may_edit(
    folder: dict[str, Any] | None, *, username: str, groups: set[str], admin: bool, editor: bool
) -> bool:
    """Whether someone changes the dashboards of ``folder`` (None: General)."""

    if not editor:
        return False
    if admin or folder is None or not folder.get("editors"):
        return True
    return _matches(folder["editors"], username, groups)


def may_see(
    folder: dict[str, Any] | None, *, username: str, groups: set[str], admin: bool, editor: bool
) -> bool:
    """Whether someone sees the dashboards of ``folder`` (None: General)."""

    if admin or folder is None or not folder.get("viewers"):
        return True
    if _matches(folder["viewers"], username, groups):
        return True
    return bool(folder.get("editors")) and may_edit(
        folder, username=username, groups=groups, admin=admin, editor=editor
    )


def _general_folders(connection: sqlite3.Connection) -> None:
    """Folders named General: an open one is folded into General (its dashboards and reports
    move there), one kept for some people is renamed "General (restricted)"."""

    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    names = {
        str(row[0]).casefold() for row in connection.execute("SELECT name FROM dashboard_folders")
    }
    rows = connection.execute(
        "SELECT folder_id, viewers_json, editors_json FROM dashboard_folders "
        "WHERE lower(trim(name)) = ?",
        (RESERVED,),
    ).fetchall()
    for folder_id, viewers, editors in rows:
        if viewers in ("", "[]") and editors in ("", "[]"):
            for table in ("dashboards", "reports"):
                if table in tables:
                    connection.execute(
                        f"UPDATE {table} SET folder_id = '' WHERE folder_id = ?", (folder_id,)
                    )
            connection.execute("DELETE FROM dashboard_folders WHERE folder_id = ?", (folder_id,))
            continue
        name, n = "General (restricted)", 2
        while name.casefold() in names:
            name, n = f"General (restricted {n})", n + 1
        names.add(name.casefold())
        connection.execute(
            "UPDATE dashboard_folders SET name = ? WHERE folder_id = ?", (name, folder_id)
        )


class FolderStore(Store):
    MIGRATIONS = (Migration("2026-10-26-general-reserved", _general_folders),)

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS dashboard_folders (
        folder_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        viewers_json TEXT NOT NULL DEFAULT '[]',
        editors_json TEXT NOT NULL DEFAULT '[]',
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_by TEXT,
        updated_at TEXT NOT NULL
    );
    """
    _JSON = {"viewers": ("viewers_json", []), "editors": ("editors_json", [])}

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM dashboard_folders ORDER BY name COLLATE NOCASE, rowid"
            ).fetchall()
        return [self._row_with_json(row, self._JSON) for row in rows]

    def get(self, folder_id: str) -> dict[str, Any] | None:
        if not folder_id:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dashboard_folders WHERE folder_id = ?", (folder_id,)
            ).fetchone()
        return self._row_with_json(row, self._JSON) if row else None

    def by_name(self, name: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT folder_id FROM dashboard_folders WHERE name = ? COLLATE NOCASE",
                (name.strip(),),
            ).fetchone()
        return self.get(row["folder_id"]) if row else None

    def count(self) -> int:
        with self._lock, self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM dashboard_folders").fetchone()[0])

    def create(self, payload: dict[str, Any], user: str | None) -> dict[str, Any]:
        folder_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dashboard_folders
                (folder_id, name, description, viewers_json, editors_json, created_by,
                 created_at, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    folder_id,
                    payload["name"],
                    payload.get("description") or "",
                    self._json(payload.get("viewers") or []),
                    self._json(payload.get("editors") or []),
                    user,
                    now,
                    user,
                    now,
                ),
            )
        return self.get(folder_id) or {}

    def update(self, folder_id: str, payload: dict[str, Any], user: str | None) -> dict | None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE dashboard_folders SET name = ?, description = ?, viewers_json = ?,
                    editors_json = ?, updated_by = ?, updated_at = ?
                WHERE folder_id = ?
                """,
                (
                    payload["name"],
                    payload.get("description") or "",
                    self._json(payload.get("viewers") or []),
                    self._json(payload.get("editors") or []),
                    user,
                    self._now(),
                    folder_id,
                ),
            )
        return self.get(folder_id) if cursor.rowcount else None

    def delete(self, folder_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM dashboard_folders WHERE folder_id = ?", (folder_id,)
            )
        return bool(cursor.rowcount)
