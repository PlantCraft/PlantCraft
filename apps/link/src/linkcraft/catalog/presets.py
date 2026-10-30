"""Algorithms (stored as rows of ``method_profiles``) and the site's method defaults.

A row's ``method_config`` holds the algorithm: ``diagram`` (version 2, ``linkcraft.blocks``),
``docs`` (its documentation), ``subject_kind`` (``loop`` or ``signal``) and, derived from the
diagram, ``method_ids`` and ``parameters``. Beside it, who made the algorithm (``author``; "PlantCraft"
for Link's own), who answers for it (``owner``), free ``tags``, the user group that may edit it
(``group_id``: the others read it) and its ``version``, one more at each save; each version is
kept in ``algorithm_versions`` (its name, description and diagram as saved). Rows of version 0.2 (a method list, a version 1
``flow``) are converted when the monitor starts (``loops.monitor``). The table keeps its name so
an update needs no copy.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from linkcraft.catalog.loop_types import algorithm_id
from linkcraft.db import Migration, Store, add_columns
from linkcraft.i18n import t

SHIPPED_AUTHOR = "PlantCraft"


class PresetStore(Store):
    """Persist presets and defaults that any application can apply to its methods."""

    # Added in 0.4.0 (Link round 6, one list of algorithms): column: declaration.
    COLUMNS = {
        "author": "TEXT NOT NULL DEFAULT ''",
        "owner": "TEXT NOT NULL DEFAULT ''",
        "owner_name": "TEXT NOT NULL DEFAULT ''",
        "tags_json": "TEXT NOT NULL DEFAULT '[]'",
        "group_id": "TEXT NOT NULL DEFAULT ''",
        "version": "INTEGER NOT NULL DEFAULT 1",
    }
    # Added in 0.5.0 (Link round 9 review, D19): a version's own name and what changed in it.
    VERSION_COLUMNS = {
        "version_name": "TEXT NOT NULL DEFAULT ''",
        "version_note": "TEXT NOT NULL DEFAULT ''",
    }
    MIGRATIONS = (
        Migration("columns-before-0.5", add_columns("method_profiles", COLUMNS)),
        Migration("version-notes", add_columns("algorithm_versions", VERSION_COLUMNS)),
    )

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS method_profiles (
        profile_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        system INTEGER NOT NULL DEFAULT 0,
        method_config_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS method_defaults (
        method_id TEXT PRIMARY KEY,
        parameters_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT 'Engineering'
    );

    -- Every save of a method's or a check's defaults is a version with what changed (owner,
    -- 2026-10-27); the newest is the one in use, the others can be deleted.
    CREATE TABLE IF NOT EXISTS method_defaults_versions (
        method_id TEXT NOT NULL,
        number INTEGER NOT NULL,
        parameters_json TEXT NOT NULL,
        description TEXT NOT NULL,
        saved_by TEXT NOT NULL,
        saved_at TEXT NOT NULL,
        PRIMARY KEY (method_id, number)
    );

    -- Every saved version of an algorithm, as it was saved (versions on top).
    CREATE TABLE IF NOT EXISTS algorithm_versions (
        algorithm_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        method_config_json TEXT NOT NULL,
        saved_at TEXT NOT NULL,
        saved_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (algorithm_id, version)
    );

    -- What Link did once and must not do again (the demo plant's examples, say).
    CREATE TABLE IF NOT EXISTS link_marks (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        at TEXT NOT NULL
    );
    """

    def __init__(self, db: Any):
        super().__init__(db)
        with self._lock, self._connect() as connection:
            # Algorithms saved before 0.4 start their history with the version they are at.
            connection.execute(
                f"INSERT OR IGNORE INTO algorithm_versions {self._VERSION_ROW}",  # noqa: S608
            )

    # The current row of ``method_profiles`` as a row of ``algorithm_versions``.
    _VERSION_ROW = """
        (algorithm_id, version, name, description, method_config_json, saved_at, saved_by)
        SELECT profile_id, version, name, description, method_config_json, updated_at, author
        FROM method_profiles
    """

    @classmethod
    def _keep_version(cls, connection: Any, profile_id: str, *, replace: bool = False) -> None:
        """Keep the row's version; ``replace``: a shipped version changed in place takes over."""

        sql = f"INSERT INTO algorithm_versions {cls._VERSION_ROW} WHERE profile_id = ? AND true "  # noqa: S608
        if replace:
            sql += (
                "ON CONFLICT(algorithm_id, version) DO UPDATE SET name = excluded.name, "
                "description = excluded.description, "
                "method_config_json = excluded.method_config_json, saved_at = excluded.saved_at "
                "WHERE algorithm_versions.method_config_json != excluded.method_config_json "
                "OR algorithm_versions.name != excluded.name "
                "OR algorithm_versions.description != excluded.description"
            )
        else:
            sql += "ON CONFLICT(algorithm_id, version) DO NOTHING"
        connection.execute(sql, (profile_id,))

    def list_versions(self, algorithm_id: str) -> list[dict[str, Any]]:
        """An algorithm's versions, newest first, without their diagrams."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT v.algorithm_id, v.version, v.name, v.description, v.saved_at, v.saved_by, "
                "v.version_name, v.version_note, "
                "p.system FROM algorithm_versions v "
                "JOIN method_profiles p ON p.profile_id = v.algorithm_id "
                "WHERE v.algorithm_id = ? ORDER BY v.version DESC",
                (algorithm_id,),
            ).fetchall()
        return [self._translated(dict(row)) for row in rows]

    def get_version(self, algorithm_id: str, version: int) -> dict[str, Any] | None:
        """One version as it was saved: its name, description and ``method_config``."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT v.*, p.system FROM algorithm_versions v "
                "JOIN method_profiles p ON p.profile_id = v.algorithm_id "
                "WHERE v.algorithm_id = ? AND v.version = ?",
                (algorithm_id, int(version)),
            ).fetchone()
        if row is None:
            return None
        found = self._row_with_json(row, {"method_config": ("method_config_json", {})})
        return self._translated(found)

    def mark(self, key: str, value: str = "") -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO link_marks (key, value, at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, at = excluded.at",
                (key, value, self._now()),
            )

    def marked(self, key: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM link_marks WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def seed_system_algorithms(self, algorithms: Iterable[dict[str, Any]]) -> None:
        """Write the shipped algorithms (read-only rows) and drop shipped rows no longer shipped.

        ``algorithms`` carry ``algorithm_id``, ``name``, ``description`` and ``method_config``
        (the diagram, its documentation and what it runs on); people's own rows are untouched.
        """

        items = list(algorithms)
        now = self._now()
        with self._lock, self._connect() as connection:
            for item in items:
                connection.execute(
                    """
                    INSERT INTO method_profiles
                    (profile_id, name, description, system, method_config_json,
                     created_at, updated_at, author, owner, owner_name, tags_json, version)
                    VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        method_config_json = excluded.method_config_json,
                        updated_at = excluded.updated_at,
                        author = excluded.author,
                        owner = excluded.owner,
                        owner_name = excluded.owner_name,
                        tags_json = excluded.tags_json,
                        version = excluded.version
                    WHERE method_profiles.system = 1
                    """,
                    (
                        item["algorithm_id"],
                        item["name"],
                        item["description"],
                        self._json(item["method_config"]),
                        now,
                        now,
                        SHIPPED_AUTHOR,
                        "",
                        SHIPPED_AUTHOR,
                        self._json(list(item.get("tags") or [])),
                        int(item.get("version") or 1),
                    ),
                )
                self._keep_version(connection, item["algorithm_id"], replace=True)
            shipped = [item["algorithm_id"] for item in items]
            marks = ", ".join("?" for _ in shipped) or "''"
            for table, column in (
                ("algorithm_versions", "algorithm_id"),
                ("method_profiles", "profile_id"),
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE {column} NOT IN ({marks}) AND {column} IN "  # noqa: S608
                    f"(SELECT profile_id FROM method_profiles WHERE system = 1)",
                    shipped,
                )

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM method_profiles
                ORDER BY system DESC, name
                """
            ).fetchall()
        return [
            self._translated(
                self._row_with_json(
                    row,
                    {"method_config": ("method_config_json", {}), "tags": ("tags_json", [])},
                )
            )
            for row in rows
        ]

    @staticmethod
    def _translated(profile: dict[str, Any]) -> dict[str, Any]:
        """Link's algorithms are stored in English; serve them in the request's language."""

        if profile.get("system"):
            for key in ("name", "description"):
                if profile.get(key):
                    profile[key] = t(profile[key])
            profile["tags"] = [t(tag) for tag in profile.get("tags") or []]
        return profile

    def get_profile(self, profile_id: str | None) -> dict[str, Any] | None:
        """One algorithm; an id of a 0.2 protocol finds the algorithm that replaced it."""

        if not profile_id:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM method_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
            if row is None and algorithm_id(profile_id) != profile_id:
                row = connection.execute(
                    "SELECT * FROM method_profiles WHERE profile_id = ?",
                    (algorithm_id(profile_id),),
                ).fetchone()
        return (
            self._translated(
                self._row_with_json(
                    row,
                    {"method_config": ("method_config_json", {}), "tags": ("tags_json", [])},
                )
            )
            if row
            else None
        )

    def save_profile(
        self,
        *,
        profile_id: str,
        name: str,
        description: str,
        method_config: dict[str, Any],
        author: str = "",
        owner: str | None = None,
        owner_name: str | None = None,
        tags: list[str] | None = None,
        group_id: str | None = None,
        version_name: str = "",
        version_note: str = "",
    ) -> None:
        """Save a person's algorithm (never a shipped one: those stay read-only). A new one
        records its ``author`` (who also answers for it until someone else does); each later
        save is one version more, with its own name and what changed (``version_name``,
        ``version_note``). Owner, tags and group left as None keep what they were."""

        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO method_profiles
                (profile_id, name, description, system, method_config_json,
                 created_at, updated_at, author, owner, owner_name, tags_json, group_id, version)
                VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(profile_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    method_config_json = excluded.method_config_json,
                    updated_at = excluded.updated_at,
                    version = method_profiles.version + 1
                WHERE method_profiles.system = 0
                """,
                (
                    profile_id,
                    name,
                    description,
                    self._json(method_config),
                    now,
                    now,
                    author,
                    owner or author,
                    owner_name or owner or author,
                    self._json(_tags(tags or [])),
                    group_id or "",
                ),
            )
            self._keep_version(connection, profile_id)
            if version_name or version_note:
                connection.execute(
                    "UPDATE algorithm_versions SET version_name = ?, version_note = ? "
                    "WHERE algorithm_id = ? AND version = "
                    "(SELECT version FROM method_profiles WHERE profile_id = ?)",
                    (version_name[:120], version_note[:2000], profile_id, profile_id),
                )
        if any(value is not None for value in (owner, tags, group_id)):
            self.update_meta(
                profile_id, owner=owner, owner_name=owner_name, tags=tags, group_id=group_id
            )

    def update_meta(
        self,
        profile_id: str,
        *,
        owner: str | None = None,
        owner_name: str | None = None,
        tags: list[str] | None = None,
        group_id: str | None = None,
    ) -> bool:
        """Who answers for a person's algorithm, its tags and its group (not a new version)."""

        changes: dict[str, Any] = {}
        if owner is not None:
            changes["owner"] = owner.strip()
            changes["owner_name"] = (owner_name or owner).strip()
        if tags is not None:
            changes["tags_json"] = self._json(_tags(tags))
        if group_id is not None:
            changes["group_id"] = group_id.strip()
        if not changes:
            return self.get_profile(profile_id) is not None
        sets = ", ".join(f"{column} = ?" for column in changes)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE method_profiles SET {sets} WHERE profile_id = ? AND system = 0",
                (*changes.values(), profile_id),
            )
        return cursor.rowcount > 0

    def delete_profile(self, profile_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM method_profiles WHERE profile_id = ? AND system = 0", (profile_id,)
            )
            if cursor.rowcount:
                connection.execute(
                    "DELETE FROM algorithm_versions WHERE algorithm_id = ?", (profile_id,)
                )
        return cursor.rowcount > 0

    def list_method_defaults(self) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT method_id, parameters_json FROM method_defaults"
            ).fetchall()
        return {row["method_id"]: self._loads(row["parameters_json"], {}) for row in rows}

    def save_method_defaults(
        self,
        method_id: str,
        parameters: dict[str, Any],
        *,
        actor: str = "Engineering",
    ) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO method_defaults
                (method_id, parameters_json, updated_at, updated_by)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(method_id) DO UPDATE SET
                    parameters_json = excluded.parameters_json,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (method_id, self._json(parameters), now, actor),
            )
        return parameters

    def add_defaults_version(
        self, method_id: str, parameters: dict[str, Any], description: str, *, actor: str
    ) -> dict[str, Any]:
        """Record a save of a method's (or a check's) defaults as its next version."""

        now = self._now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(number) AS last FROM method_defaults_versions WHERE method_id = ?",
                (method_id,),
            ).fetchone()
            number = int(row["last"] or 0) + 1
            connection.execute(
                "INSERT INTO method_defaults_versions (method_id, number, parameters_json, "
                "description, saved_by, saved_at) VALUES (?, ?, ?, ?, ?, ?)",
                (method_id, number, self._json(parameters), description.strip(), actor, now),
            )
        return {"number": number, "saved_at": now}

    def defaults_versions(self, method_id: str) -> list[dict[str, Any]]:
        """A method's saved defaults, newest first; the first is the one in use."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT number, parameters_json, description, saved_by, saved_at "
                "FROM method_defaults_versions WHERE method_id = ? ORDER BY number DESC",
                (method_id,),
            ).fetchall()
        return [
            {
                "number": row["number"],
                "parameters": self._loads(row["parameters_json"], {}),
                "description": row["description"],
                "saved_by": row["saved_by"],
                "saved_at": row["saved_at"],
                "current": index == 0,
            }
            for index, row in enumerate(rows)
        ]

    def delete_defaults_version(self, method_id: str, number: int) -> bool:
        """Delete one saved version, never the one in use (the newest)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(number) AS last FROM method_defaults_versions WHERE method_id = ?",
                (method_id,),
            ).fetchone()
            if row["last"] is None or int(row["last"]) == number:
                raise ValueError(t("The version in use cannot be deleted."))
            cursor = connection.execute(
                "DELETE FROM method_defaults_versions WHERE method_id = ? AND number = ?",
                (method_id, number),
            )
        return cursor.rowcount > 0


def _tags(tags: Iterable[str]) -> list[str]:
    """Tags as people typed them: trimmed, without repeats (case aside), at most 20."""

    seen: dict[str, str] = {}
    for tag in tags:
        text = " ".join(str(tag).split())[:40]
        if text and text.lower() not in seen:
            seen[text.lower()] = text
    return list(seen.values())[:20]
