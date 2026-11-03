"""``DeskStore``'s triage of the inbox, the marks people put on what they read, and Desk's
settings. Part of ``DeskStore`` (``plantcraft.desk``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft.db import utc_text
from plantcraft.desk.common import MARKS, TRIAGE_STATES, _day, _forget_visits
from plantcraft.i18n import t


class TriageStore:
    """``DeskStore``'s triage, marks and settings."""

    # Triage -----------------------------------------------------------------------------------

    def triage(self, username: str) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT key, state, until FROM desk_triage WHERE username = ?", (username,)
            ).fetchall()
        return {row["key"]: {"state": row["state"], "until": row["until"]} for row in rows}

    def set_triage(
        self, username: str, key: str, state: str | None, until: str | None = None
    ) -> None:
        with self._lock, self._write() as connection:
            if state is None:
                connection.execute(
                    "DELETE FROM desk_triage WHERE username = ? AND key = ?", (username, key)
                )
                return
            if state not in TRIAGE_STATES:
                raise ValueError(t("Mark it read, done or snooze it."))
            connection.execute(
                "INSERT INTO desk_triage (username, key, state, until, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(username, key) DO UPDATE SET state = excluded.state, until = excluded.until, "
                "updated_at = excluded.updated_at",
                (
                    username,
                    key[:300],
                    state,
                    _day(until) if state == "snoozed" else None,
                    self._now(),
                ),
            )
            # Old entries go: a month is more than any inbox or suggestion lives.
            connection.execute(
                "DELETE FROM desk_triage WHERE username = ? AND updated_at < ?",
                (
                    username,
                    utc_text(datetime.now(timezone.utc) - timedelta(days=45)),
                ),
            )
            _forget_visits(connection, "desk_triage")

    # Marks ------------------------------------------------------------------------------------

    def marks(self, username: str, mark: str) -> set[str]:
        """The keys ``username`` marked with ``mark`` (``star`` or ``unread``)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT key FROM desk_marks WHERE username = ? AND mark = ?", (username, mark)
            ).fetchall()
        return {row["key"] for row in rows}

    def set_mark(self, username: str, key: str, mark: str, on: bool) -> None:
        if mark not in MARKS:
            raise ValueError(t("Mark it as a favorite or as unread."))
        with self._lock, self._write() as connection:
            if on:
                connection.execute(
                    "INSERT INTO desk_marks (username, key, mark, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(username, key, mark) DO UPDATE SET updated_at = excluded.updated_at",
                    (username, key[:300], mark, self._now()),
                )
            else:
                connection.execute(
                    "DELETE FROM desk_marks WHERE username = ? AND key = ? AND mark = ?",
                    (username, key[:300], mark),
                )
            _forget_visits(connection, "desk_marks")

    # Settings ---------------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        """Calendar links are off until an administrator turns them on and names the hosts
        (the platform may run with no internet, docs/security-guide.md)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM desk_settings WHERE key = 'calendar_links'"
            ).fetchone()
        value = self._loads(row["value_json"] if row else None, {})
        hosts = [str(host) for host in value.get("hosts", []) if str(host).strip()][:20]
        return {
            "calendar_links": bool(value.get("enabled")) and bool(hosts),
            "enabled": bool(value.get("enabled")),
            "hosts": hosts,
        }

    def save_settings(self, *, enabled: bool, hosts: list[str], actor: str) -> dict[str, Any]:
        names: list[str] = []
        for host in hosts[:20]:
            name = str(host).strip().lower().lstrip("*.").rstrip(".")
            if not name:
                continue
            if "/" in name or ":" in name or " " in name or "." not in name:
                raise ValueError(
                    t(
                        "{host} is not a host name (outlook.office365.com, calendar.google.com).",
                        host=host,
                    )
                )
            names.append(name)
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO desk_settings (key, value_json, updated_by, updated_at) VALUES ('calendar_links', ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_by = excluded.updated_by, "
                "updated_at = excluded.updated_at",
                (
                    self._json({"enabled": bool(enabled), "hosts": list(dict.fromkeys(names))}),
                    actor,
                    self._now(),
                ),
            )
        return self.settings()

    def team_page(self) -> bool:
        """Desk's Team page is hidden until an administrator shows it (its use
        is not clear yet; nothing it reads is lost meanwhile)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM desk_settings WHERE key = 'team_page'"
            ).fetchone()
        return bool(self._loads(row["value_json"] if row else None, {}).get("enabled"))

    def save_team_page(self, enabled: bool, *, actor: str) -> bool:
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO desk_settings (key, value_json, updated_by, updated_at) VALUES ('team_page', ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_by = excluded.updated_by, "
                "updated_at = excluded.updated_at",
                (self._json({"enabled": bool(enabled)}), actor, self._now()),
            )
        return self.team_page()
