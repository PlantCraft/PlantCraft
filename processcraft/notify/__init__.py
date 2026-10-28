"""Notifications the apps send to people and groups: in Messages always, by email when set up.

An app (its service token) calls ``POST /api/v1/notifications`` with recipients
(``user:<username>`` or ``group:<id>``), a title, a text, a priority and a link back. The
platform resolves the groups, so apps never hold anyone's email. Each person gets the message in
their conversation with the app's robot user ("Alarms"), where the suite's messages button
already counts it. When an administrator configured an SMTP server (Settings, Email) and the
person allows it in their profile, an email is queued too: the outbox is sent by a background
worker, retried while the server is down, and at most ``HOURLY_LIMIT`` emails an hour go to one
person; what waits beyond it leaves in one digest. Nothing here opens a connection to anything
but the SMTP server the administrator chose. See docs/notifications.md.
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any

from processcraft.auth.users import is_email
from processcraft.db import Database, Store, utc_text
from processcraft.files import write_atomic
from processcraft.i18n import t

LOGGER = logging.getLogger(__name__)

PRIORITIES = ("critical", "high", "medium", "low")
MAX_RECIPIENTS = 50
MAX_TITLE = 200
MAX_TEXT = 3000
HOURLY_LIMIT = 20
# How long a settled thread is remembered (Messages' feed shows 30 days).
RESOLUTION_DAYS = 45
MAX_ATTEMPTS = 6
TICK_SECONDS = 20
SECURITY = ("starttls", "tls", "none")
PREFERENCE_KEY = "notifications"
DEFAULT_PREFERENCES = {"email": True, "email_min_priority": "high"}


def priority_label(priority: str) -> str:
    return {
        "critical": t("Critical"),
        "high": t("High"),
        "medium": t("Medium"),
        "low": t("Low"),
    }.get(priority, priority)


def _rank(priority: str) -> int:
    return PRIORITIES.index(priority) if priority in PRIORITIES else len(PRIORITIES)


def preferences(raw: Any) -> dict[str, Any]:
    """A person's notification preferences, completed with the defaults."""

    found = dict(DEFAULT_PREFERENCES)
    if isinstance(raw, dict):
        if isinstance(raw.get("email"), bool):
            found["email"] = raw["email"]
        if raw.get("email_min_priority") in PRIORITIES:
            found["email_min_priority"] = raw["email_min_priority"]
    return found


class SecretFile:
    """One secret (the SMTP password) in a JSON file with mode 600, beside the database."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def get(self) -> str | None:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        value = data.get("smtp_password") if isinstance(data, dict) else None
        return str(value) if value else None

    def set(self, value: str | None) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, json.dumps({"smtp_password": value or ""}))


@dataclass(frozen=True)
class MailSettings:
    enabled: bool = False
    host: str = ""
    port: int = 587
    security: str = "starttls"
    username: str = ""
    sender: str = ""
    verify_certificate: bool = True

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.host) and bool(self.sender)

    def public(self, has_password: bool) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "security": self.security,
            "username": self.username,
            "sender": self.sender,
            "verify_certificate": self.verify_certificate,
            "has_password": has_password,
            "ready": self.ready,
        }


def check_settings(payload: dict[str, Any]) -> MailSettings:
    host = str(payload.get("host") or "").strip()
    sender = str(payload.get("sender") or "").strip()
    security = str(payload.get("security") or "starttls")
    if security not in SECURITY:
        raise ValueError(t("Security is STARTTLS, TLS or none."))
    try:
        port = int(payload.get("port") or (465 if security == "tls" else 587))
    except (TypeError, ValueError) as exc:
        raise ValueError(t("The port is a number from 1 to 65535.")) from exc
    if not 1 <= port <= 65535:
        raise ValueError(t("The port is a number from 1 to 65535."))
    if any(char.isspace() for char in host) or len(host) > 253:
        raise ValueError(t("Enter the server's name or address, without spaces."))
    if sender and (not is_email(sender) or len(sender) > 200):
        raise ValueError(t("Enter a valid sender address."))
    enabled = bool(payload.get("enabled"))
    if enabled and (not host or not sender):
        raise ValueError(t("To send email, fill in the server and the sender address."))
    return MailSettings(
        enabled=enabled,
        host=host,
        port=port,
        security=security,
        username=str(payload.get("username") or "").strip()[:200],
        sender=sender,
        verify_certificate=payload.get("verify_certificate") is not False,
    )


def one_line(text: str) -> str:
    """``text`` as a header can carry it: line breaks and other control characters as spaces."""

    return " ".join("".join(char if char.isprintable() else " " for char in text).split())


def send_mail(
    settings: MailSettings, password: str | None, to: str, subject: str, body: str
) -> None:
    """One email through the configured server; raises ``OSError``/``smtplib.SMTPException``,
    and ``ValueError`` for an address that is not one plain address."""

    if not is_email(to):
        raise ValueError(t("{address} is not a valid email address.", address=one_line(to)[:200]))
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = to
    message["Subject"] = one_line(subject)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=settings.sender.split("@")[-1])
    message.set_content(body)
    context = ssl.create_default_context()
    if not settings.verify_certificate:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if settings.security == "tls":
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.host, settings.port, timeout=15, context=context
        )
    else:
        server = smtplib.SMTP(settings.host, settings.port, timeout=15)
    with server:
        if settings.security == "starttls":
            server.starttls(context=context)
        if settings.username:
            server.login(settings.username, password or "")
        server.send_message(message)


class NotificationStore(Store):
    """Mail settings, the email outbox and each person's conversation with each app."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS mail_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS notification_threads (
        app_id TEXT NOT NULL,
        username TEXT NOT NULL,
        conversation_id INTEGER NOT NULL,
        PRIMARY KEY (app_id, username)
    );

    CREATE TABLE IF NOT EXISTS notification_outbox (
        email_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        address TEXT NOT NULL,
        app_id TEXT NOT NULL,
        priority TEXT NOT NULL,
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        sent_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_notification_outbox_status
    ON notification_outbox(status, username);

    -- What the app said is settled (an alarm acknowledged or cleared), per app and key, for every
    -- person who received it: docs/quick-access.md (2026-10-26).
    CREATE TABLE IF NOT EXISTS notification_resolutions (
        app_id TEXT NOT NULL,
        key TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        resolved_at TEXT NOT NULL,
        PRIMARY KEY (app_id, key)
    );
    """

    def settings(self) -> MailSettings:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM mail_settings WHERE id = 1"
            ).fetchone()
        data = self._loads(row["payload_json"], {}) if row else {}
        try:
            return check_settings({**data, "enabled": bool(data.get("enabled"))})
        except ValueError:
            return MailSettings()

    def save_settings(self, settings: MailSettings, username: str) -> None:
        payload = {
            "enabled": settings.enabled,
            "host": settings.host,
            "port": settings.port,
            "security": settings.security,
            "username": settings.username,
            "sender": settings.sender,
            "verify_certificate": settings.verify_certificate,
        }
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO mail_settings (id, payload_json, updated_at, updated_by)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at, updated_by = excluded.updated_by
                """,
                (self._json(payload), self._now(), username),
            )

    def thread(self, app_id: str, username: str) -> int | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT conversation_id FROM notification_threads WHERE app_id = ? AND username = ?",
                (app_id, username),
            ).fetchone()
        return int(row["conversation_id"]) if row else None

    def set_thread(self, app_id: str, username: str, conversation_id: int) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO notification_threads (app_id, username, conversation_id) VALUES (?, ?, ?)
                ON CONFLICT(app_id, username) DO UPDATE SET conversation_id = excluded.conversation_id
                """,
                (app_id, username, conversation_id),
            )

    def resolve(self, app_id: str, key: str, note: str) -> str:
        """Settles the thread ``key`` of ``app_id`` for everyone; the time it was written."""

        moment = self._now()
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO notification_resolutions (app_id, key, note, resolved_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(app_id, key) DO UPDATE SET note = excluded.note,
                    resolved_at = excluded.resolved_at
                """,
                (app_id, key, note, moment),
            )
            cutoff = utc_text(datetime.now(timezone.utc) - timedelta(days=RESOLUTION_DAYS))
            connection.execute(
                "DELETE FROM notification_resolutions WHERE resolved_at < ?", (cutoff,)
            )
        return moment

    def resolutions(self, app_ids: list[str]) -> dict[tuple[str, str], dict[str, str]]:
        """Every settled thread of these apps: ``{(app, key): {"note", "at"}}``."""

        if not app_ids:
            return {}
        marks = ",".join("?" for _ in app_ids)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM notification_resolutions WHERE app_id IN ({marks})",
                list(app_ids),
            ).fetchall()
        return {
            (row["app_id"], row["key"]): {"note": row["note"], "at": row["resolved_at"]}
            for row in rows
        }

    def queue(
        self, username: str, address: str, app_id: str, priority: str, subject: str, body: str
    ) -> int:
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                """
                INSERT INTO notification_outbox
                (username, address, app_id, priority, subject, body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (username, address, app_id, priority, subject, body, self._now()),
            )
        return int(cursor.lastrowid)

    def pending(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notification_outbox WHERE status = 'pending' ORDER BY email_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def sent_since(self, username: str, moment: str) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM notification_outbox
                WHERE username = ? AND status = 'sent' AND sent_at >= ?
                """,
                (username, moment),
            ).fetchone()
        return int(row[0])

    def mark(self, ids: list[int], status: str, error: str = "") -> None:
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        now = self._now()
        with self._lock, self._write() as connection:
            if status == "retry":
                connection.execute(
                    f"""
                    UPDATE notification_outbox SET attempts = attempts + 1, last_error = ?,
                        status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END
                    WHERE email_id IN ({marks})
                    """,
                    [error[:500], MAX_ATTEMPTS, *ids],
                )
            else:
                connection.execute(
                    f"""
                    UPDATE notification_outbox SET status = ?, last_error = ?,
                        sent_at = CASE WHEN ? = 'sent' THEN ? ELSE sent_at END
                    WHERE email_id IN ({marks})
                    """,
                    [status, error[:500], status, now, *ids],
                )

    def outbox_counts(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM notification_outbox GROUP BY status"
            ).fetchall()
            last = connection.execute(
                """
                SELECT last_error, created_at FROM notification_outbox
                WHERE last_error != '' ORDER BY email_id DESC LIMIT 1
                """
            ).fetchone()
        counts = {row["status"]: int(row["total"]) for row in rows}
        return {
            "pending": counts.get("pending", 0),
            "sent": counts.get("sent", 0),
            "failed": counts.get("failed", 0),
            "last_error": last["last_error"] if last else "",
            "last_error_at": last["created_at"] if last else None,
        }


class NotificationCenter:
    """Delivers notifications: the message in the app, the email in the outbox."""

    def __init__(
        self,
        db: Database,
        users: Any,
        groups: Any,
        messages: Any,
        preferences_store: Any,
        secret: SecretFile,
    ):
        self.store = NotificationStore(db)
        self.users = users
        self.groups = groups
        self.messages = messages
        self.preferences_store = preferences_store
        self.secret = secret
        self._sending = threading.Lock()

    # Settings ----------------------------------------------------------------------

    def public_settings(self) -> dict[str, Any]:
        return {
            **self.store.settings().public(bool(self.secret.get())),
            "outbox": self.store.outbox_counts(),
        }

    def save_settings(self, payload: dict[str, Any], username: str) -> dict[str, Any]:
        settings = check_settings(payload)
        password = payload.get("password")
        before = self.store.settings()
        moved = (before.host, before.port, before.username) != (
            settings.host,
            settings.port,
            settings.username,
        )
        if moved and not password and not payload.get("clear_password") and self.secret.get():
            # The saved password only goes to the server it was typed for: whoever changes the
            # server types it again (security audit 2026-10-22).
            raise ValueError(
                t(
                    "The server changed: type the password again, so the saved one is never sent "
                    "to another server."
                )
            )
        if isinstance(password, str) and password:
            self.secret.set(password)
        elif payload.get("clear_password"):
            self.secret.set(None)
        self.store.save_settings(settings, username)
        return self.public_settings()

    def test(self, to: str) -> None:
        """Sends a test email now (raises with the server's answer when it fails)."""

        settings = self.store.settings()
        if not settings.host or not settings.sender:
            raise ValueError(t("Fill in the server and the sender address first."))
        send_mail(
            settings,
            self.secret.get(),
            to,
            t("PlantCraft: test email"),
            t("This is a test from PlantCraft. Email notifications can reach you."),
        )

    # Preferences -------------------------------------------------------------------

    def preferences(self, username: str) -> dict[str, Any]:
        return preferences(self.preferences_store.get(username, PREFERENCE_KEY))

    def set_preferences(self, username: str, payload: dict[str, Any]) -> dict[str, Any]:
        cleaned = preferences(payload)
        self.preferences_store.put(username, PREFERENCE_KEY, cleaned)
        return cleaned

    # Recipients --------------------------------------------------------------------

    def expand(self, recipients: list[str]) -> tuple[list[str], list[str]]:
        """``user:``/``group:`` references -> (active people, references not found)."""

        people: list[str] = []
        unknown: list[str] = []
        for ref in recipients:
            kind, _, name = str(ref).strip().partition(":")
            name = name.strip().lower()
            if kind == "user" and name:
                user = self.users.get_user(name)
                if user and user.get("active") and user.get("kind", "person") == "person":
                    people.append(name)
                else:
                    unknown.append(ref)
            elif kind == "group" and name and self.groups.get(name) is not None:
                people.extend(self.groups.members(name))
            else:
                unknown.append(ref)
        return list(dict.fromkeys(people)), unknown

    # Delivery ----------------------------------------------------------------------

    def _robot(self, app_id: str, app_name: str) -> str:
        """The app's robot user, who signs its messages ("Alarms")."""

        found = self.users.get_user(app_id)
        if found is not None and found.get("kind") == "person":
            raise PermissionError(
                t("A person's username matches this app's id: {app}.", app=app_id)
            )
        if found is None or found.get("display_name") != app_name or not found.get("active"):
            self.users.upsert_user(app_id, app_name, t("App notifications"), kind="system")
        return app_id

    def _conversation(self, app_id: str, robot: str, app_name: str, username: str) -> int:
        known = self.store.thread(app_id, username)
        if known is not None and self.messages.get(known) is not None:
            if self.messages.is_member(known, username) and self.messages.is_member(known, robot):
                return known
        started = self.messages.start(robot, [username], title=app_name)
        conversation_id = int(started["conversation_id"])
        self.store.set_thread(app_id, username, conversation_id)
        return conversation_id

    def notify(
        self,
        app_id: str,
        app_name: str,
        *,
        recipients: list[str],
        title: str,
        text: str = "",
        priority: str = "medium",
        url: str | None = None,
        email: bool = False,
        refs: list[str] | None = None,
        key: str | None = None,
        category: str | None = None,
        actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        people, unknown = self.expand(recipients)
        robot = self._robot(app_id, app_name)
        label = priority_label(priority)
        body = f"**{title}**" + (f"\n\n{text}" if text else "")
        settings = self.store.settings()
        delivered: list[str] = []
        queued = 0
        for username in people:
            conversation_id = self._conversation(app_id, robot, app_name, username)
            self.messages.post(
                conversation_id,
                robot,
                body,
                refs=refs,
                meta={
                    "kind": "notification",
                    "app": app_id,
                    "priority": priority,
                    "priority_label": label,
                    "url": url,
                    "key": key,
                    "category": category,
                    "actions": actions or [],
                },
            )
            delivered.append(username)
            if not (email and settings.ready):
                continue
            wanted = self.preferences(username)
            if not wanted["email"] or _rank(priority) > _rank(wanted["email_min_priority"]):
                continue
            address = ((self.users.get_user(username) or {}).get("profile") or {}).get("email")
            if not address:
                continue
            lines = [text] if text else []
            if url:
                lines.append(t("Open: {url}", url=url))
            self.store.queue(
                username,
                address,
                app_id,
                priority,
                f"[{label}] {title}"[:250],
                "\n\n".join(lines) or title,
            )
            queued += 1
        return {"delivered": delivered, "email_queued": queued, "unknown": unknown}

    def resolve(self, app_id: str, key: str, note: str = "") -> dict[str, Any]:
        """The app settled what it notified about under ``key`` (an alarm acknowledged or
        cleared): the thread leaves everyone's unread count and loses its buttons, showing
        ``note`` ("Acknowledged by Ana"). A later notification with the same key opens it again."""

        moment = self.store.resolve(app_id, key, note)
        return {"key": key, "resolved_at": moment, "note": note}

    # The outbox --------------------------------------------------------------------

    def flush(self, *, now: datetime | None = None) -> dict[str, int]:
        """Sends what waits in the outbox; one digest when a person has several waiting."""

        settings = self.store.settings()
        if not settings.ready:
            return {"sent": 0, "waiting": len(self.store.pending())}
        moment = now or datetime.now(timezone.utc)
        hour_ago = utc_text(moment - timedelta(hours=1))
        by_person: dict[str, list[dict[str, Any]]] = {}
        for item in self.store.pending():
            by_person.setdefault(item["username"], []).append(item)
        password = self.secret.get()
        sent = waiting = 0
        with self._sending:
            for username, items in by_person.items():
                if self.store.sent_since(username, hour_ago) >= HOURLY_LIMIT:
                    waiting += len(items)
                    continue
                ids = [item["email_id"] for item in items]
                if len(items) == 1:
                    subject, body = items[0]["subject"], items[0]["body"]
                else:
                    items.sort(key=lambda item: (_rank(item["priority"]), item["email_id"]))
                    subject = t("{count} notifications from PlantCraft", count=len(items))
                    body = "\n\n---\n\n".join(
                        f"{item['subject']}\n{item['body']}" for item in items
                    )
                try:
                    send_mail(settings, password, items[-1]["address"], subject, body)
                except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
                    LOGGER.warning("notifications: email to %s failed: %s", username, exc)
                    self.store.mark(ids, "retry", str(exc))
                    waiting += len(items)
                    continue
                except ValueError as exc:
                    # This email can never go (an address or text a header cannot carry): it
                    # fails alone, and the people after it still get theirs.
                    LOGGER.warning("notifications: email to %s refused: %s", username, exc)
                    self.store.mark(ids, "failed", str(exc))
                    continue
                self.store.mark(ids, "sent")
                sent += len(items)
        return {"sent": sent, "waiting": waiting}

    def run(self, stop: threading.Event, seconds: float = TICK_SECONDS) -> None:
        while not stop.wait(seconds):
            try:
                self.flush()
            except Exception:  # the outbox never stops for one bad tick
                LOGGER.exception("notifications: flush failed")
