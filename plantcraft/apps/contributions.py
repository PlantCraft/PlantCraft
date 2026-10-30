"""The registry of what each app adds to PlantCraft (``docs/app-standard.md``, section 4b).

An app declares in ``app.toml`` what PlantCraft draws for it (``[contributes]``: its uses of a
language model, widgets, search, calendar feeds, to-do kinds, reference kinds, installation
settings, Settings pages, work queue) and the series it writes to the Historian
(``[[publishes.series]]``). The SDK's server sends all of it when the app starts
(``PUT /api/v1/contributions``); an app with no app key carries it in its metrics instead, which
PlantCraft's monitor reads every minute. One row per app, replaced whole; every screen reads
this registry, so a new app reaches them without a change to the platform.

Tables a newer app sends that this PlantCraft does not know are kept aside (``unknown``) and
shown in Operations, never refused: the app still starts and the rest is drawn.
"""

from __future__ import annotations

import logging
from typing import Any

from plantcraft.db import Store
from plantcraft_sdk.contributes import ContributionsIn

LOGGER = logging.getLogger(__name__)


class ContributionStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS app_contributions (
        app TEXT PRIMARY KEY,
        version TEXT NOT NULL DEFAULT '',
        body_json TEXT NOT NULL DEFAULT '{}',
        unknown_json TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL
    );
    """

    def put(self, app: str, body: ContributionsIn) -> dict[str, Any]:
        """What ``app`` adds, replaced; answers the stored row."""

        data = body.model_dump(
            mode="json", exclude_none=True, exclude={"app", "version", "unknown", "events"}
        )
        if body.unknown:
            LOGGER.warning(
                "%s declares tables this PlantCraft does not draw: %s",
                app,
                ", ".join(body.unknown),
            )
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO app_contributions (app, version, body_json, unknown_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(app) DO UPDATE SET version = excluded.version,
                    body_json = excluded.body_json, unknown_json = excluded.unknown_json,
                    updated_at = excluded.updated_at
                """,
                (app, body.version, self._json(data), self._json(body.unknown), self._now()),
            )
        return self.get(app) or {}

    def get(self, app: str) -> dict[str, Any] | None:
        """One app's row; None when it never sent its contributions."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM app_contributions WHERE app = ?", (app,)
            ).fetchone()
        return None if row is None else self._item(row)

    def listing(self, apps: list[str] | None = None) -> list[dict[str, Any]]:
        """Every app's row by app id; ``apps`` keeps those (the apps installed now)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM app_contributions ORDER BY app").fetchall()
        items = [self._item(row) for row in rows]
        if apps is None:
            return items
        order = {app: index for index, app in enumerate(apps)}
        return sorted(
            (item for item in items if item["app"] in order), key=lambda item: order[item["app"]]
        )

    def _item(self, row: Any) -> dict[str, Any]:
        body = self._loads(row["body_json"], {})
        return {
            "app": row["app"],
            "version": row["version"],
            "format": body.get("format", 1),
            "contributes": body.get("contributes", {}),
            "series": body.get("series", []),
            # Its [permissions] as ids; None from an app before SDK 0.42 (plantcraft.apps.scopes).
            "permissions": body.get("permissions"),
            "unknown": self._loads(row["unknown_json"], []),
            "updated_at": row["updated_at"],
        }


def summary(item: dict[str, Any]) -> dict[str, int]:
    """How many of each kind an app adds, for the Apps page ("2 widgets, 1 use of a model")."""

    contributes = item.get("contributes") or {}
    counts = {
        key: len(value) for key, value in contributes.items() if isinstance(value, list) and value
    }
    if contributes.get("search"):
        counts["search"] = 1
    if contributes.get("queue"):
        counts["queue"] = 1
    if item.get("series"):
        counts["series"] = len(item["series"])
    return counts


__all__ = ["ContributionStore", "summary"]
