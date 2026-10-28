"""The installation settings of each app, set in Settings › Apps (``docs/app-standard.md``, 4b).

An app declares them in ``[[contributes.settings]]`` (key, title, help, type, default...);
PlantCraft draws them, keeps what the administrator chose and gives the app its values at
``GET /api/v1/contributions/settings``. Only a value differing from the default is kept; a
secret one is never shown again, only to the app. They live in PlantCraft's database, so the
backup carries them with the rest of Settings.
"""

from __future__ import annotations

from typing import Any

from processcraft.db import Store
from plantcraft_sdk.contributes import setting_value


class AppSettingStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS app_setting_values (
        app TEXT NOT NULL,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        PRIMARY KEY (app, key)
    );
    """

    def stored(self, app: str) -> dict[str, Any]:
        """What the administrator chose for ``app``, by key."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value_json FROM app_setting_values WHERE app = ?", (app,)
            ).fetchall()
        return {row["key"]: self._loads(row["value_json"], None) for row in rows}

    def values(self, app: str, specs: list[dict[str, Any]]) -> dict[str, Any]:
        """Every declared setting's value: the chosen one, else its default."""

        chosen = self.stored(app)
        return {spec["key"]: chosen.get(spec["key"], spec.get("default")) for spec in specs}

    def save(
        self, app: str, specs: list[dict[str, Any]], changes: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        """``changes`` checked against ``specs`` and kept (None: back to the default). Raises
        ValueError for an unknown key or a value outside its rules; answers what changed."""

        by_key = {spec["key"]: spec for spec in specs}
        unknown = sorted(set(changes) - set(by_key))
        if unknown:
            raise ValueError(f"{app} has no setting {', '.join(unknown)}.")
        checked = {key: setting_value(by_key[key], value) for key, value in changes.items()}
        now = self._now()
        with self._lock, self._write() as connection:
            for key, value in checked.items():
                if value is None or value == by_key[key].get("default"):
                    connection.execute(
                        "DELETE FROM app_setting_values WHERE app = ? AND key = ?", (app, key)
                    )
                    continue
                connection.execute(
                    """
                    INSERT INTO app_setting_values (app, key, value_json, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(app, key) DO UPDATE SET value_json = excluded.value_json,
                        updated_at = excluded.updated_at, updated_by = excluded.updated_by
                    """,
                    (app, key, self._json(value), now, actor),
                )
        return checked


__all__ = ["AppSettingStore"]
