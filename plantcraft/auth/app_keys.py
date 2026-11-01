"""Keys an app uses to ask PlantCraft for a service token (``PLANTCRAFT_APP_KEY``).

An administrator creates a key for an app id; the key is shown once and only
its SHA-256 is stored (the key is 256 random bits, so a plain digest is
enough; no password stretching needed). Revoked keys stop working at once,
and so do the service tokens issued with them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime
from typing import Any

from plantcraft.db import Database, Migration, Store, add_columns
from plantcraft.i18n import t
from plantcraft_sdk.scopes import PERMISSIONS

PREFIX = "pck"
APP_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def check_scopes(scopes: Any) -> list[str] | None:
    """A key's scopes: None (all the app's permissions) or a list of known permissions."""

    if scopes is None:
        return None
    unknown = sorted({str(item) for item in scopes} - set(PERMISSIONS))
    if unknown:
        raise ValueError(t("Unknown permissions: {names}.", names=", ".join(unknown)))
    return sorted({str(item) for item in scopes})


def check_app_id(app_id: str) -> str:
    app_id = (app_id or "").strip().lower()
    if not APP_ID.match(app_id):
        raise ValueError(t("Invalid app id: use lower-case letters, digits, hyphen or underscore."))
    return app_id


class AppKeyStore(Store):
    """App keys: who created them, when they were last used and whether they are revoked."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS app_keys (
        key_id TEXT PRIMARY KEY,
        app_id TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        key_hash TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL,
        revoked_at TEXT,
        revoked_by TEXT,
        last_used_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_app_keys_app ON app_keys(app_id);
    """
    MIGRATIONS = (
        # A key may hold less than its app's permissions (backlog B8, 2026-10-31): NULL is all
        # of them, a JSON list only those (a read-only key for a collector, say).
        Migration("key-scopes", add_columns("app_keys", {"scopes_json": "TEXT"})),
    )

    def __init__(self, db: Database):
        super().__init__(db)

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        item = dict(row)
        item.pop("key_hash", None)
        item["active"] = item["revoked_at"] is None
        raw = item.pop("scopes_json", None)
        try:
            scopes = None if raw is None else json.loads(raw)
        except (TypeError, ValueError):
            scopes = []  # an unreadable list grants nothing
        item["scopes"] = None if scopes is None else [str(x) for x in scopes]
        return item

    def create(
        self,
        app_id: str,
        *,
        label: str = "",
        actor: str | None = None,
        scopes: list[str] | None = None,
    ) -> tuple[dict, str]:
        """A new key for ``app_id``: its record and the key itself (shown once, never stored).
        ``scopes``: the permissions its tokens hold, within the app's own; None: all of them."""

        app_id = check_app_id(app_id)
        scopes = check_scopes(scopes)
        key_id = secrets.token_hex(6)
        secret = secrets.token_urlsafe(32)
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO app_keys
                    (key_id, app_id, label, key_hash, created_by, created_at, scopes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key_id,
                    app_id,
                    label.strip()[:120],
                    _digest(secret),
                    actor,
                    self._now(),
                    None if scopes is None else json.dumps(scopes),
                ),
            )
        return self.get(key_id) or {}, f"{PREFIX}_{key_id}.{secret}"

    def get(self, key_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM app_keys WHERE key_id = ?", (key_id,)
            ).fetchone()
        return self._public(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM app_keys ORDER BY revoked_at IS NOT NULL, app_id, created_at DESC"
            ).fetchall()
        return [self._public(row) for row in rows]

    def revoke(self, key_id: str, *, actor: str | None = None) -> dict[str, Any] | None:
        with self._lock, self._write() as connection:
            connection.execute(
                """
                UPDATE app_keys SET revoked_at = ?, revoked_by = ?
                WHERE key_id = ? AND revoked_at IS NULL
                """,
                (self._now(), actor, key_id),
            )
        return self.get(key_id)

    def verify(self, app_id: str, key: str) -> dict[str, Any] | None:
        """The active key record matching ``app_id`` and ``key``, or None."""

        prefix, _, rest = (key or "").partition("_")
        key_id, _, secret = rest.partition(".")
        if prefix != PREFIX or not key_id or not secret:
            return None
        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT * FROM app_keys WHERE key_id = ? AND revoked_at IS NULL", (key_id,)
            ).fetchone()
            if row is None or row["app_id"] != app_id:
                return None
            if not hmac.compare_digest(row["key_hash"], _digest(secret)):
                return None
            connection.execute(
                "UPDATE app_keys SET last_used_at = ? WHERE key_id = ?", (self._now(), key_id)
            )
        return self._public(row)

    def is_active(self, key_id: str) -> bool:
        item = self.get(key_id)
        return bool(item and item["active"])

    def revoked_since(self, moment: float) -> list[tuple[str, int]]:
        """``(key_id, revoked_at in Unix seconds)`` of keys revoked after ``moment``."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT key_id, revoked_at FROM app_keys WHERE revoked_at IS NOT NULL ORDER BY key_id"
            ).fetchall()
        revoked = []
        for row in rows:
            try:
                stamp = int(datetime.fromisoformat(row["revoked_at"]).timestamp())
            except (TypeError, ValueError):
                continue
            if stamp > moment:
                revoked.append((row["key_id"], stamp))
        return revoked
