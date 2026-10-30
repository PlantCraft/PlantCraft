"""The apps installed from PlantCraft (packages, the catalog, external apps), pending uploads
and the administrator's switches (the online catalog).

Apps listed in ``PLANTCRAFT_APPS`` are not stored here: that setting stays
the way to configure them by hand (``plantcraft/auth/suite.py``).
"""

from __future__ import annotations

from typing import Any

from plantcraft.db import Database, Store

# Statuses: installing, updating, rolling_back, removing, key (waiting for the installer);
# running, failed (the installer's outcome); external (registered by address only).
PENDING = {"installing", "updating", "rolling_back", "removing", "key"}
LAUNCHABLE = {"running", "external", "updating", "rolling_back", "key"}
JSON_FIELDS = {
    "publisher": ("publisher_json", {}),
    "permissions": ("permissions_json", []),
    "manifest": ("manifest_json", {}),
    "health": ("health_json", None),
}


class InstalledAppStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS installed_apps (
        app_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        version TEXT,
        url TEXT NOT NULL,
        origin TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        publisher_json TEXT,
        permissions_json TEXT,
        manifest_json TEXT,
        previous_version TEXT,
        request_id TEXT,
        request_action TEXT,
        prior_status TEXT,
        key_id TEXT,
        health_json TEXT,
        installed_by TEXT,
        installed_at TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS installed_app_sboms (
        app_id TEXT NOT NULL,
        version TEXT NOT NULL,
        sbom_json TEXT NOT NULL,
        PRIMARY KEY (app_id, version)
    );

    CREATE TABLE IF NOT EXISTS app_uploads (
        upload_id TEXT PRIMARY KEY,
        origin TEXT NOT NULL,
        app_id TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        sbom_json TEXT NOT NULL,
        sbom_summary_json TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS app_install_settings (
        name TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_by TEXT,
        updated_at TEXT NOT NULL
    );
    """

    def __init__(self, db: Database):
        super().__init__(db)

    def _public(self, row: Any) -> dict[str, Any]:
        return self._row_with_json(row, JSON_FIELDS)

    # Installed apps ------------------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM installed_apps ORDER BY app_id").fetchall()
        return [self._public(row) for row in rows]

    def get(self, app_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM installed_apps WHERE app_id = ?", (app_id,)
            ).fetchone()
        return self._public(row) if row else None

    def save(self, app_id: str, **fields: Any) -> dict[str, Any]:
        """Creates or updates one app; JSON fields are given by their public names."""

        values: dict[str, Any] = {}
        for name, value in fields.items():
            if name in JSON_FIELDS:
                values[JSON_FIELDS[name][0]] = None if value is None else self._json(value)
            else:
                values[name] = value
        values["updated_at"] = self._now()
        with self._lock, self._write() as connection:
            exists = connection.execute(
                "SELECT 1 FROM installed_apps WHERE app_id = ?", (app_id,)
            ).fetchone()
            if exists:
                assignments = ", ".join(f"{column} = ?" for column in values)
                connection.execute(
                    f"UPDATE installed_apps SET {assignments} WHERE app_id = ?",
                    [*values.values(), app_id],
                )
            else:
                values.setdefault("installed_at", values["updated_at"])
                columns = ["app_id", *values]
                connection.execute(
                    f"INSERT INTO installed_apps ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    [app_id, *values.values()],
                )
        return self.get(app_id) or {}

    def delete(self, app_id: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM installed_apps WHERE app_id = ?", (app_id,))

    # SBOMs ---------------------------------------------------------------------------------

    def save_sbom(self, app_id: str, version: str, document: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO installed_app_sboms (app_id, version, sbom_json) "
                "VALUES (?, ?, ?)",
                (app_id, version, document),
            )

    def sbom(self, app_id: str, version: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT sbom_json FROM installed_app_sboms WHERE app_id = ? AND version = ?",
                (app_id, version),
            ).fetchone()
        return str(row[0]) if row else None

    # Uploads waiting for the administrator's confirmation -----------------------------------

    def add_upload(
        self,
        upload_id: str,
        *,
        origin: str,
        summary: dict[str, Any],
        sbom: str,
        sbom_summary: dict[str, Any],
        created_by: str,
    ) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO app_uploads (upload_id, origin, app_id, summary_json, sbom_json,
                    sbom_summary_json, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    upload_id,
                    origin,
                    summary["id"],
                    self._json(summary),
                    sbom,
                    self._json(sbom_summary),
                    created_by,
                    self._now(),
                ),
            )

    def upload(self, upload_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM app_uploads WHERE upload_id = ?", (upload_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_with_json(
            row,
            {"summary": ("summary_json", {}), "sbom_summary": ("sbom_summary_json", {})},
        )

    def uploads(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT upload_id, created_at FROM app_uploads ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_upload(self, upload_id: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM app_uploads WHERE upload_id = ?", (upload_id,))

    # Switches set by an administrator on the Apps page ---------------------------------------

    def setting(self, name: str, default: str = "") -> str:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_install_settings WHERE name = ?", (name,)
            ).fetchone()
        return str(row[0]) if row else default

    def set_setting(self, name: str, value: str, actor: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO app_install_settings (name, value, updated_by, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (name, value, actor, self._now()),
            )
