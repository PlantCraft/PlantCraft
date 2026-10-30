"""Saved dashboards and their public links, shared by everyone in the installation."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.server.store import Database, Migration, Store, add_columns

from dashcraft.dashboards.legacy import place_cards, upgrade_dashboard
from dashcraft.dashboards.model import GRID_VERSION, Conflict

_JSON_FIELDS = {
    "cards": ("cards_json", []),
    "pages": ("pages_json", []),
    "variables": ("variables_json", []),
    "tags": ("tags_json", []),
}
_FLAGS = ("shared_cursor", "kiosk")
# The saves kept per dashboard (Config › Versions): the newest ones, to look at and restore.
MAX_VERSIONS = 30
# What a version keeps: the dashboard as its editors saved it (not where it is filed).
_VERSIONED = (
    "name",
    "description",
    "context_kind",
    "variables",
    "refresh_seconds",
    "pages",
    "page_seconds",
    "cards",
    "tags",
    "default_window",
    "shared_cursor",
    "kiosk",
)
# Columns added after the first release (the store's ``MIGRATIONS``; never edit ``SCHEMA`` for
# them). ``grid`` defaults to 1 so rows saved before it are known and migrated once.
_ADDED_COLUMNS = {
    "pages_json": "TEXT NOT NULL DEFAULT '[]'",
    "page_seconds": "INTEGER NOT NULL DEFAULT 0",
    "grid": "INTEGER NOT NULL DEFAULT 1",
    # A dashboard the suite keeps (``suite-health``): read-only, one of each; '' for people's.
    "builtin": "TEXT NOT NULL DEFAULT ''",
    # Round 6 (2026-10-23): the folder ('' = General), tags, the window it opens with, the
    # cursor shared by its charts and full screen without the toolbar.
    "folder_id": "TEXT NOT NULL DEFAULT ''",
    "tags_json": "TEXT NOT NULL DEFAULT '[]'",
    "default_window": "TEXT NOT NULL DEFAULT ''",
    "shared_cursor": "INTEGER NOT NULL DEFAULT 0",
    "kiosk": "INTEGER NOT NULL DEFAULT 0",
    # Round 7 (2026-10-24): the dashboard's variables (``variables.py``).
    "variables_json": "TEXT NOT NULL DEFAULT '[]'",
}
# One-off clean-ups, each run once per database (``dashboard_marks``).
_CLEANUP_COPIES = "2026-10-23-copies"
_SHARE_COLUMNS = (
    "share_id, dashboard_id, label, created_by, created_at, last_used_at, expires_at, target"
)
MAX_TOKEN_LENGTH = 200


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class DashboardStore(Store):
    MIGRATIONS = (
        Migration("columns-before-0.5", add_columns("dashboards", _ADDED_COLUMNS)),
        # 2026-10-26: a link opens a dashboard or a report (its id in ``dashboard_id``).
        Migration(
            "2026-10-26-report-links",
            add_columns("dashboard_shares", {"target": "TEXT NOT NULL DEFAULT 'dashboard'"}),
        ),
        # 2026-10-27: a link lasts what its author chose (90 days unless
        # said otherwise); links made before stay until revoked (``expires_at`` empty).
        Migration(
            "2026-10-27-link-expiry", add_columns("dashboard_shares", {"expires_at": "TEXT"})
        ),
    )

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS dashboards (
        dashboard_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        context_kind TEXT,
        refresh_seconds INTEGER NOT NULL DEFAULT 60,
        cards_json TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_by TEXT,
        updated_at TEXT NOT NULL
    );

    -- Public links: whoever has the token sees that one dashboard, read-only.
    -- Only the token's SHA-256 is kept; the link is shown once, when created.
    CREATE TABLE IF NOT EXISTS dashboard_shares (
        share_id TEXT PRIMARY KEY,
        dashboard_id TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL DEFAULT '',
        created_by TEXT,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT,
        revoked_by TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_dashboard_shares_dashboard ON dashboard_shares(dashboard_id);

    -- The last saves of each dashboard (Config › Versions).
    CREATE TABLE IF NOT EXISTS dashboard_versions (
        dashboard_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        saved_by TEXT,
        saved_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        PRIMARY KEY (dashboard_id, version)
    );

    -- One-off clean-ups already run on this database.
    CREATE TABLE IF NOT EXISTS dashboard_marks (
        name TEXT PRIMARY KEY,
        at TEXT NOT NULL
    );
    """

    def __init__(self, db: Database):
        super().__init__(db)
        with self._lock, self._connect() as connection:
            self._migrate_grid(connection)
            self._remove_untouched_copies(connection)

    def _migrate_grid(self, connection: sqlite3.Connection) -> None:
        """Grid 1 to 2: a card's height counts rows of half the old row (short 1 is 2 rows,
        tall 2 is 4), so every saved dashboard keeps its look. Not a person's save."""

        rows = connection.execute(
            "SELECT dashboard_id, cards_json, pages_json, context_kind, variables_json, grid "
            "FROM dashboards WHERE grid < ?",
            (GRID_VERSION,),
        ).fetchall()
        for row in rows:
            cards = [card for card in self._loads(row["cards_json"], []) if isinstance(card, dict)]
            if row["grid"] < 2:
                for card in cards:
                    card["height"] = 4 if card.get("height") == 2 else 2
            # Grid 3 (round 7): the card shape of fields.py and a place on the grid for each.
            upgraded = upgrade_dashboard(
                {
                    "context_kind": row["context_kind"],
                    "variables": self._loads(row["variables_json"], []),
                    "cards": cards,
                }
            )
            pages = [page for page in self._loads(row["pages_json"], []) if isinstance(page, dict)]
            first = pages[0].get("page_id") if pages else None
            connection.execute(
                "UPDATE dashboards SET cards_json = ?, variables_json = ?, grid = ? "
                "WHERE dashboard_id = ?",
                (
                    self._json(place_cards(upgraded["cards"], first)),
                    self._json(upgraded["variables"]),
                    GRID_VERSION,
                    row["dashboard_id"],
                ),
            )

    def _remove_untouched_copies(self, connection: sqlite3.Connection) -> None:
        """Once: the empty "New dashboard" left by opening the editor without saving (before
        round 6 the button saved at once), and the repeats of a dashboard nobody changed after
        it was made (the starter button made them again at every click). The oldest of each
        repeat stays; a dashboard someone saved since it was made is never touched."""

        if connection.execute(
            "SELECT 1 FROM dashboard_marks WHERE name = ?", (_CLEANUP_COPIES,)
        ).fetchone():
            return
        rows = connection.execute(
            "SELECT dashboard_id, name, cards_json, pages_json, created_at, updated_at "
            "FROM dashboards WHERE builtin = '' ORDER BY created_at, rowid"
        ).fetchall()
        seen: set[tuple[str, str, str]] = set()
        removed = []
        for row in rows:
            if row["updated_at"] != row["created_at"]:
                continue
            key = (row["name"], row["cards_json"], row["pages_json"])
            empty_new = row["name"] == "New dashboard" and self._loads(row["cards_json"], []) == []
            if empty_new or key in seen:
                removed.append(row["dashboard_id"])
            seen.add(key)
        for dashboard_id in removed:
            shared = connection.execute(
                "SELECT 1 FROM dashboard_shares WHERE dashboard_id = ? AND revoked_at IS NULL",
                (dashboard_id,),
            ).fetchone()
            if not shared:
                connection.execute("DELETE FROM dashboards WHERE dashboard_id = ?", (dashboard_id,))
        connection.execute(
            "INSERT INTO dashboard_marks (name, at) VALUES (?, ?)", (_CLEANUP_COPIES, self._now())
        )

    # Dashboards ----------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM dashboards ORDER BY updated_at DESC, rowid"
            ).fetchall()
            counts = dict(
                connection.execute(
                    "SELECT dashboard_id, COUNT(*) FROM dashboard_shares "
                    "WHERE revoked_at IS NULL AND target = 'dashboard' "
                    "AND (expires_at IS NULL OR expires_at > ?) GROUP BY dashboard_id",
                    (self._now(),),
                ).fetchall()
            )
        items = [self._dashboard(row) for row in rows]
        for item in items:
            item["public_links"] = counts.get(item["dashboard_id"], 0)
        return items

    def get(self, dashboard_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dashboards WHERE dashboard_id = ?", (dashboard_id,)
            ).fetchone()
        return self._dashboard(row) if row else None

    def _dashboard(self, row: sqlite3.Row) -> dict[str, Any]:
        item = self._row_with_json(row, _JSON_FIELDS)
        item.pop("grid", None)
        for flag in _FLAGS:
            item[flag] = bool(item.get(flag))
        item["default_window"] = item.get("default_window") or None
        return item

    def builtin(self, name: str) -> dict[str, Any] | None:
        """The dashboard the suite keeps under ``name``, if it was created."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT dashboard_id FROM dashboards WHERE builtin = ?", (name,)
            ).fetchone()
        return self.get(row["dashboard_id"]) if row else None

    def create(
        self, payload: dict[str, Any], user: str | None, *, builtin: str = ""
    ) -> dict[str, Any]:
        dashboard_id = uuid.uuid4().hex[:12]
        now = self._now()
        values = self._values(payload)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dashboards
                (dashboard_id, name, description, context_kind, refresh_seconds, cards_json,
                 pages_json, page_seconds, grid, builtin, folder_id, tags_json, default_window,
                 shared_cursor, kiosk, variables_json, created_by, created_at, updated_by,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dashboard_id,
                    *values[:7],
                    GRID_VERSION,
                    builtin,
                    *values[7:],
                    user,
                    now,
                    user,
                    now,
                ),
            )
            self._record_version(connection, dashboard_id, payload, user, now)
        return self.get(dashboard_id) or {}

    def _values(self, payload: dict[str, Any]) -> tuple[Any, ...]:
        """The columns a person saves, in the order ``create`` and ``update`` write them."""

        return (
            payload["name"],
            payload.get("description") or "",
            payload.get("context_kind"),
            int(payload.get("refresh_seconds", 60)),
            self._json(payload.get("cards") or []),
            self._json(payload.get("pages") or []),
            int(payload.get("page_seconds") or 0),
            payload.get("folder_id") or "",
            self._json(payload.get("tags") or []),
            payload.get("default_window") or "",
            int(bool(payload.get("shared_cursor"))),
            int(bool(payload.get("kiosk"))),
            self._json(payload.get("variables") or []),
        )

    def _record_version(
        self,
        connection: sqlite3.Connection,
        dashboard_id: str,
        payload: dict[str, Any],
        user: str | None,
        at: str,
    ) -> None:
        last = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM dashboard_versions WHERE dashboard_id = ?",
            (dashboard_id,),
        ).fetchone()[0]
        kept = {key: payload.get(key) for key in _VERSIONED}
        connection.execute(
            "INSERT INTO dashboard_versions (dashboard_id, version, saved_by, saved_at, "
            "payload_json) VALUES (?, ?, ?, ?, ?)",
            (dashboard_id, int(last) + 1, user, at, self._json(kept)),
        )
        connection.execute(
            "DELETE FROM dashboard_versions WHERE dashboard_id = ? AND version <= ?",
            (dashboard_id, int(last) + 1 - MAX_VERSIONS),
        )

    def versions(self, dashboard_id: str) -> list[dict[str, Any]]:
        """The saves kept of one dashboard, newest first (without their content)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT version, saved_by, saved_at, payload_json FROM dashboard_versions "
                "WHERE dashboard_id = ? ORDER BY version DESC",
                (dashboard_id,),
            ).fetchall()
        out = []
        for row in rows:
            kept = self._loads(row["payload_json"], {})
            out.append(
                {
                    "version": row["version"],
                    "saved_by": row["saved_by"],
                    "saved_at": row["saved_at"],
                    "name": kept.get("name") or "",
                    "cards": len(kept.get("cards") or []),
                    "pages": len(kept.get("pages") or []),
                }
            )
        return out

    def version(self, dashboard_id: str, version: int) -> dict[str, Any] | None:
        """One kept save: the dashboard's content as it was then."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT version, saved_by, saved_at, payload_json FROM dashboard_versions "
                "WHERE dashboard_id = ? AND version = ?",
                (dashboard_id, version),
            ).fetchone()
        if row is None:
            return None
        return {
            "version": row["version"],
            "saved_by": row["saved_by"],
            "saved_at": row["saved_at"],
            "dashboard": self._loads(row["payload_json"], {}),
        }

    def update(
        self,
        dashboard_id: str,
        payload: dict[str, Any],
        user: str | None,
        *,
        base_updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Save a dashboard; with ``base_updated_at``, refuse when someone saved it since."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT updated_at FROM dashboards WHERE dashboard_id = ?", (dashboard_id,)
            ).fetchone()
            if row is None:
                return None
            if base_updated_at and row["updated_at"] != base_updated_at:
                raise Conflict(self.get(dashboard_id) or {})
            at = self._after(row["updated_at"])
            connection.execute(
                """
                UPDATE dashboards SET name = ?, description = ?, context_kind = ?,
                    refresh_seconds = ?, cards_json = ?, pages_json = ?, page_seconds = ?,
                    folder_id = ?, tags_json = ?, default_window = ?, shared_cursor = ?,
                    kiosk = ?, variables_json = ?, grid = ?, updated_by = ?, updated_at = ?
                WHERE dashboard_id = ?
                """,
                (*self._values(payload), GRID_VERSION, user, at, dashboard_id),
            )
            self._record_version(connection, dashboard_id, payload, user, at)
        return self.get(dashboard_id)

    def move(self, dashboard_id: str, folder_id: str) -> None:
        """File a dashboard in another folder; not a save of its content."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE dashboards SET folder_id = ? WHERE dashboard_id = ?",
                (folder_id, dashboard_id),
            )

    def in_folder(self, folder_id: str) -> int:
        with self._lock, self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM dashboards WHERE folder_id = ?", (folder_id,)
                ).fetchone()[0]
            )

    def signal_ids(self) -> set[str]:
        """Every signal id the saved cards name directly."""

        return {
            item["signal_id"]
            for dashboard in self.list()
            for card in dashboard["cards"]
            for item in card.get("items", [])
            if item.get("signal_id")
        }

    def rename_signals(self, renames: dict[str, str]) -> int:
        """Rewrite cards' signal ids (``{old: new}``); returns the dashboards changed.

        Not a person's save: ``updated_at`` stays, so an editor's open draft still saves; a
        draft that brings an old id back is renamed again at the next start.
        """

        changed = 0
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT dashboard_id, cards_json FROM dashboards").fetchall()
            for row in rows:
                cards = self._row_with_json(row, _JSON_FIELDS)["cards"]
                moved = False
                for card in cards:
                    for item in card.get("items", []):
                        new = renames.get(item.get("signal_id") or "")
                        if new:
                            item["signal_id"], moved = new, True
                if moved:
                    connection.execute(
                        "UPDATE dashboards SET cards_json = ? WHERE dashboard_id = ?",
                        (self._json(cards), row["dashboard_id"]),
                    )
                    changed += 1
        return changed

    def _after(self, previous: str) -> str:
        """Now, or 1 ms after ``previous``: every save gets a new ``updated_at``, so two saves in
        the same millisecond still conflict."""

        now = self._now()
        last = datetime.fromisoformat(previous)
        if datetime.fromisoformat(now) > last:
            return now
        return (last + timedelta(milliseconds=1)).isoformat(timespec="milliseconds")

    def delete(self, dashboard_id: str, user: str | None = None) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM dashboards WHERE dashboard_id = ?", (dashboard_id,)
            )
            connection.execute(
                "DELETE FROM dashboard_versions WHERE dashboard_id = ?", (dashboard_id,)
            )
            # A deleted dashboard's links stop working.
            connection.execute(
                "UPDATE dashboard_shares SET revoked_at = ?, revoked_by = ? "
                "WHERE dashboard_id = ? AND target = 'dashboard' AND revoked_at IS NULL",
                (self._now(), user, dashboard_id),
            )
        return bool(cursor.rowcount)

    # Public links --------------------------------------------------------------
    # A link opens one dashboard or, since 2026-10-26, one report (``target``); the id it opens is
    # kept in ``dashboard_id`` either way.

    def create_share(
        self,
        dashboard_id: str,
        user: str | None,
        label: str = "",
        target: str = "dashboard",
        days: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        """A new public link, opening for ``days`` (``None``: until revoked); returns the record
        and the token (never stored in clear)."""

        token = secrets.token_urlsafe(32)
        share_id = uuid.uuid4().hex[:12]
        now = self._now()
        expires = (
            (datetime.fromisoformat(now) + timedelta(days=days)).isoformat(timespec="milliseconds")
            if days
            else None
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dashboard_shares
                (share_id, dashboard_id, token_hash, label, created_by, created_at, target,
                 expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (share_id, dashboard_id, _digest(token), label.strip(), user, now, target, expires),
            )
        return self.share(share_id) or {}, token

    def share(self, share_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT {_SHARE_COLUMNS} FROM dashboard_shares WHERE share_id = ?", (share_id,)
            ).fetchone()
        return dict(row) if row else None

    def shares(self, dashboard_id: str, target: str = "dashboard") -> list[dict[str, Any]]:
        """The active links of one dashboard (or report), newest first."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_SHARE_COLUMNS} FROM dashboard_shares
                WHERE dashboard_id = ? AND target = ? AND revoked_at IS NULL
                    AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC, rowid DESC
                """,
                (dashboard_id, target, self._now()),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_shares(self) -> list[dict[str, Any]]:
        """Every link that still opens something, of every dashboard and report, newest first
        (what an administrator reviews)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_SHARE_COLUMNS} FROM dashboard_shares
                WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC, rowid DESC
                """,
                (self._now(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_share(
        self, dashboard_id: str, share_id: str, user: str | None, target: str = "dashboard"
    ) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE dashboard_shares SET revoked_at = ?, revoked_by = ?
                WHERE share_id = ? AND dashboard_id = ? AND target = ? AND revoked_at IS NULL
                """,
                (self._now(), user, share_id, dashboard_id, target),
            )
        return bool(cursor.rowcount)

    def revoke_all(self, dashboard_id: str, user: str | None, target: str) -> None:
        """Every link of a deleted report (a deleted dashboard's go in ``delete``)."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE dashboard_shares SET revoked_at = ?, revoked_by = ? "
                "WHERE dashboard_id = ? AND target = ? AND revoked_at IS NULL",
                (self._now(), user, dashboard_id, target),
            )

    def resolve_share(self, token: str, target: str = "dashboard") -> str | None:
        """The dashboard (or report) an active token opens, or None."""

        if not token or len(token) > MAX_TOKEN_LENGTH:
            return None
        with self._lock, self._connect() as connection:
            now = self._now()
            row = connection.execute(
                "SELECT share_id, dashboard_id FROM dashboard_shares "
                "WHERE token_hash = ? AND target = ? AND revoked_at IS NULL "
                "AND (expires_at IS NULL OR expires_at > ?)",
                (_digest(token), target, now),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE dashboard_shares SET last_used_at = ? WHERE share_id = ?",
                (now, row["share_id"]),
            )
        return str(row["dashboard_id"])
