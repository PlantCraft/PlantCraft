"""Temporary support access: an administrator lets a person into Operations for a few hours.

An integrator's engineer or someone from IT who is called for a problem gets, while the grant
lasts, the Operations role (``plantcraft.auth.access.OPERATIONS_APP``): the suite's status, load
and logs, and every request. Nothing else changes: their level, their apps and their roles stay
as they were. A grant has an end (at most ``MAX_HOURS`` ahead), a reason and, often, the request
it is for; it ends by itself or when an administrator ends it earlier. Granting and ending are in
the audit log (``operations.support_access.*``), and the person is told.

A person whose company's access ended (``GroupStore.access_ended``) cannot sign in at all, grant
or not. docs/operations.md, section 4.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from plantcraft.db import Store, utc_text
from plantcraft.i18n import t

MAX_HOURS = 72
MAX_REASON = 300


def _now() -> datetime:
    """Now on the clock every stored time uses (the demo's, in a public demo)."""

    return datetime.fromisoformat(utc_text().replace("Z", "+00:00"))


class SupportAccessStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS support_access (
        grant_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        reason TEXT NOT NULL,
        action_id INTEGER,
        granted_by TEXT NOT NULL,
        starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        ended_by TEXT,
        ended_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_support_access_person ON support_access(username, ends_at);
    """

    def grant(
        self,
        username: str,
        *,
        hours: float,
        reason: str,
        actor: str,
        action_id: int | None = None,
    ) -> dict[str, Any]:
        """Lets ``username`` into Operations for ``hours``; ``ValueError`` on a bad length or no
        reason. A person with an open grant gets its end moved instead of a second one."""

        cleaned = (reason or "").strip()[:MAX_REASON]
        if not cleaned:
            raise ValueError(t("Say why the access is needed."))
        try:
            length = float(hours)
        except (TypeError, ValueError) as exc:
            raise ValueError(t("Give the access in hours.")) from exc
        if not 0 < length <= MAX_HOURS:
            raise ValueError(t("Support access lasts up to {count} hours.", count=MAX_HOURS))
        now = _now()
        ends = utc_text(now + timedelta(hours=length))
        current = self.active(username)
        with self._lock, self._write() as connection:
            if current:
                connection.execute(
                    "UPDATE support_access SET ends_at = ?, reason = ?, action_id = ?, "
                    "granted_by = ? WHERE grant_id = ?",
                    (ends, cleaned, action_id, actor, current["grant_id"]),
                )
                grant_id = int(current["grant_id"])
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO support_access
                    (username, reason, action_id, granted_by, starts_at, ends_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (username, cleaned, action_id, actor, utc_text(now), ends),
                )
                grant_id = int(cursor.lastrowid)
        return self.get(grant_id) or {}

    def end(self, grant_id: int, *, actor: str) -> dict[str, Any]:
        """Ends a grant now; ``KeyError`` when there is none, ``ValueError`` when it already
        ended."""

        found = self.get(grant_id)
        if found is None:
            raise KeyError(grant_id)
        if not found["active"]:
            raise ValueError(t("This access already ended."))
        now = utc_text()
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE support_access SET ended_by = ?, ended_at = ?, ends_at = ? "
                "WHERE grant_id = ?",
                (actor, now, now, grant_id),
            )
        return self.get(grant_id) or {}

    def active(self, username: str) -> dict[str, Any] | None:
        """The person's grant in force now, if any (an indexed query: read on every request)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM support_access WHERE username = ? AND ends_at > ? "
                "AND ended_at IS NULL ORDER BY ends_at DESC LIMIT 1",
                (username, utc_text()),
            ).fetchone()
        return self._present(row) if row else None

    def get(self, grant_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM support_access WHERE grant_id = ?", (grant_id,)
            ).fetchone()
        return self._present(row) if row else None

    def recent(self, days: int = 30) -> list[dict[str, Any]]:
        """The grants in force and those that ended in the last ``days``, newest first."""

        since = utc_text(_now() - timedelta(days=days))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item.*, person.display_name, granter.display_name AS granted_by_name
                FROM support_access AS item
                LEFT JOIN workspace_users AS person ON person.username = item.username
                LEFT JOIN workspace_users AS granter ON granter.username = item.granted_by
                WHERE item.ends_at > ? ORDER BY item.ends_at DESC LIMIT 200
                """,
                (since,),
            ).fetchall()
        return [self._present(row) for row in rows]

    @staticmethod
    def _present(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["grant_id"] = int(item["grant_id"])
        item["active"] = item["ended_at"] is None and item["ends_at"] > utc_text()
        item.setdefault("display_name", None)
        item["display_name"] = item.get("display_name") or item["username"]
        item["granted_by_name"] = item.get("granted_by_name") or item["granted_by"]
        return item
