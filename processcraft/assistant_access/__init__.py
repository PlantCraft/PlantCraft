"""AI assistant access: the read-only MCP server's switch and the people's access tokens.

An administrator turns the MCP server on in Settings (it is off by default, and
``PLANTCRAFT_MCP=off`` keeps it off for good in an installation). Then each person may create
an access token for their own AI assistant (Claude, or any client that speaks MCP). The token is
shown once and only its SHA-256 is stored, like an app key (``auth/app_keys.py``). It acts as its
owner, read-only, with the owner's current access, and expires after at most ``max_days``.
Revoking a token, turning the server off, or the owner losing access stops it at once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.utc import parse_instant
from processcraft.config import env_flag
from processcraft.db import Database, Store, utc_text

PREFIX = "pcat"
DEFAULT_DAYS = 30
MAX_DAYS = 365
# Active tokens one person may hold at a time.
MAX_PER_PERSON = 10


def mcp_allowed() -> bool:
    """False when the installation turned the MCP server off for good."""

    return env_flag("PLANTCRAFT_MCP", True)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class AssistantAccessStore(Store):
    """The MCP switch (one row) and the access tokens."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS assistant_access_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        enabled INTEGER NOT NULL DEFAULT 0,
        max_days INTEGER NOT NULL DEFAULT 30,
        updated_by TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS assistant_tokens (
        token_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        token_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        revoked_by TEXT,
        last_used_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_assistant_tokens_user ON assistant_tokens(username);
    """

    def __init__(self, db: Database):
        super().__init__(db)

    # Settings -------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_access_settings WHERE id = 1"
            ).fetchone()
        allowed = mcp_allowed()
        stored = dict(row) if row else {"enabled": 0, "max_days": DEFAULT_DAYS}
        return {
            "allowed": allowed,
            "enabled": allowed and bool(stored["enabled"]),
            "max_days": int(stored["max_days"]),
            "updated_by": stored.get("updated_by"),
            "updated_at": stored.get("updated_at"),
        }

    def save_settings(self, *, enabled: bool, max_days: int, actor: str) -> dict[str, Any]:
        max_days = max(1, min(MAX_DAYS, int(max_days)))
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO assistant_access_settings (id, enabled, max_days, updated_by, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled,
                    max_days = excluded.max_days, updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (int(bool(enabled)), max_days, actor, self._now()),
            )
        return self.settings()

    def enabled(self) -> bool:
        return self.settings()["enabled"]

    # Tokens ---------------------------------------------------------------------------

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        item = dict(row)
        item.pop("token_hash", None)
        expired = _expired(item["expires_at"])
        item["active"] = item["revoked_at"] is None and not expired
        item["expired"] = expired
        return item

    def longest_days(self, longest: int | None = None) -> int:
        """How many days a new token may last: the administrator's ``max_days``, or less."""

        cap = self.settings()["max_days"]
        return max(1, min(MAX_DAYS, cap, longest or cap))

    def create(
        self, username: str, *, label: str = "", days: int | None = None, longest: int | None = None
    ) -> tuple[dict[str, Any], str]:
        """A new token for ``username``: its record and the token itself (shown once).

        It lasts ``days``, at most the administrator's ``max_days``; ``longest`` caps it further
        (the Notebooks kit's tokens, ``notebooks.kits.KIT_TOKEN_DAYS``), never past ``max_days``
        (security audit, 2026-10-26)."""

        cap = self.longest_days(longest)
        days = max(1, min(cap, int(days or cap)))
        if len([item for item in self.list(username) if item["active"]]) >= MAX_PER_PERSON:
            raise ValueError(f"at most {MAX_PER_PERSON} active tokens per person")
        token_id = secrets.token_hex(6)
        secret = secrets.token_urlsafe(32)
        expires = utc_text(datetime.now(timezone.utc) + timedelta(days=days))
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO assistant_tokens
                    (token_id, username, label, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token_id, username, label.strip()[:120], _digest(secret), self._now(), expires),
            )
        return self.get(token_id) or {}, f"{PREFIX}_{token_id}.{secret}"

    def get(self, token_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_tokens WHERE token_id = ?", (token_id,)
            ).fetchone()
        return self._public(row) if row else None

    def list(self, username: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM assistant_tokens"
        values: tuple[Any, ...] = ()
        if username is not None:
            query += " WHERE username = ?"
            values = (username,)
        query += " ORDER BY revoked_at IS NOT NULL, created_at DESC"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._public(row) for row in rows]

    def revoke(self, token_id: str, *, actor: str) -> dict[str, Any] | None:
        with self._lock, self._write() as connection:
            connection.execute(
                """
                UPDATE assistant_tokens SET revoked_at = ?, revoked_by = ?
                WHERE token_id = ? AND revoked_at IS NULL
                """,
                (self._now(), actor, token_id),
            )
        return self.get(token_id)

    def verify(self, token: str) -> dict[str, Any] | None:
        """The active token record ``token`` names, or None (wrong, revoked or expired)."""

        prefix, _, rest = (token or "").partition("_")
        token_id, _, secret = rest.partition(".")
        if prefix != PREFIX or not token_id or not secret:
            return None
        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_tokens WHERE token_id = ? AND revoked_at IS NULL",
                (token_id,),
            ).fetchone()
            if row is None or not hmac.compare_digest(row["token_hash"], _digest(secret)):
                return None
            if _expired(row["expires_at"]):
                return None
            connection.execute(
                "UPDATE assistant_tokens SET last_used_at = ? WHERE token_id = ?",
                (self._now(), token_id),
            )
        return self._public(row)


def _expired(expires_at: str | None) -> bool:
    moment = parse_instant(expires_at)
    return moment is None or moment <= datetime.now(timezone.utc)
