"""The conditions an app reports in its metrics, written as that app's events.

The Historian answers the suite and never calls it: it has no app key, so it cannot post events.
It names the conditions it has open now in ``GET /api/ops/metrics`` instead
(``plantcraft_sdk.server.ops.report_conditions``), with its event catalog. Each minute the
health recorder (``plantcraft.watch.recorder``) reads every server's metrics and hands them
here: the relay keeps the app's catalog, compares the conditions with the ones the app reported
before and writes, in the app's name, a ``start`` for each new one and an ``end`` for each one
gone. Alarms then judges them like any other event.

A condition whose payload names ``owners`` (``user:``/``group:`` references: the owners of a
Historian source, H13) is also told to them as a notification of the app, with an email, under
the key ``condition:<key>``; when it ends, that notification is settled ("Back to normal at
…"). The owners of a failing integration hear of it without anyone writing an alarm rule.

An app that did not answer this minute keeps its conditions open: not knowing is not good news,
and the suite watch already says the app is down. Open conditions are stored, so a restart
neither repeats a start nor forgets an end. A condition whose name the app does not declare as
an ``interval`` event is left out and logged once.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from plantcraft.config import plant_clock
from plantcraft.db import Migration, Store, add_columns
from plantcraft.i18n import t
from plantcraft.refs import parse_ref
from plantcraft_sdk.contributes import ContributionsIn
from plantcraft_sdk.events import CatalogIn

LOGGER = logging.getLogger(__name__)

ACTOR = "system"
MAX_OWNERS = 20
# Where a condition about a source opens, by app.
APP_PAGES = {"histcraft": "/hist/sources/{source}"}
# The notification's priority for the event's severity.
PRIORITIES = {"critical": "critical", "error": "high", "warning": "medium", "info": "low"}


class ConditionRelay(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS relayed_conditions (
        app TEXT NOT NULL,
        condition_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        subject TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        opened_at TEXT NOT NULL,
        PRIMARY KEY (app, condition_key)
    );
    """
    # Who was told when the condition opened (a JSON list), to settle it when it ends (H13).
    MIGRATIONS = (
        Migration(
            "owners", add_columns("relayed_conditions", {"owners": "TEXT NOT NULL DEFAULT '[]'"})
        ),
    )

    def __init__(
        self,
        db: Any,
        events: Any,
        contributions: Any = None,
        *,
        notifications: Callable[[], Any] | None = None,
        app_names: Callable[[], dict[str, str]] | None = None,
    ):
        """``notifications`` answers the suite's ``NotificationCenter`` (it is built after the
        relay); ``app_names`` the apps' display names."""

        super().__init__(db)
        self.events = events
        self.notifications = notifications
        self.app_names = app_names
        # The registry of what apps add (plantcraft.apps.contributions), fed the same way.
        self.contributions = contributions
        self._catalogs: dict[str, str] = {}
        self._contributed: dict[str, str] = {}
        self._warned: set[tuple[str, str]] = set()

    def apply(self, reported: dict[str, dict[str, Any]]) -> dict[str, int]:
        """``reported``: app -> its metrics, for the apps that answered. Answers the conditions
        opened and closed."""

        opened = closed = 0
        for app, answer in sorted(reported.items()):
            if isinstance(answer.get("events"), list):
                self._put_catalog(app, answer["events"])
            if isinstance(answer.get("contributions"), dict):
                self._put_contributions(app, answer["contributions"])
            conditions = answer.get("conditions")
            if not isinstance(conditions, list):
                continue  # the app reports none (or could not read them this time)
            try:
                now = self._declared(app, conditions)
                before = self.open_conditions(app)
                for key, item in now.items():
                    if key not in before:
                        self._start(app, key, item)
                        opened += 1
                for key, row in before.items():
                    if key not in now:
                        self._end(app, key, row)
                        closed += 1
            except Exception:  # one app's conditions never stop the others
                LOGGER.exception("conditions of %s not written", app)
        return {"opened": opened, "closed": closed}

    def open_conditions(self, app: str | None = None) -> dict[str, dict[str, Any]]:
        """key -> the stored condition (of ``app``, or of every app keyed ``app/key``)."""

        with self._lock, self._connect() as connection:
            if app is None:
                rows = connection.execute("SELECT * FROM relayed_conditions").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM relayed_conditions WHERE app = ?", (app,)
                ).fetchall()
        return {
            (row["condition_key"] if app else f"{row['app']}/{row['condition_key']}"): dict(row)
            for row in rows
        }

    # Inside ---------------------------------------------------------------------------------

    def _put_catalog(self, app: str, catalog: list[Any]) -> None:
        try:
            specs = CatalogIn.model_validate({"events": catalog}).events
        except ValidationError as exc:
            self._warn(app, "catalog", f"event catalog of {app} refused: {exc.errors()[0]['msg']}")
            return
        events = [spec.model_dump(mode="json", exclude_none=True) for spec in specs]
        text = self._json(events)
        if self._catalogs.get(app) == text:
            return
        self.events.put_catalog(app, events)
        self._catalogs[app] = text

    def _put_contributions(self, app: str, body: dict[str, Any]) -> None:
        if self.contributions is None:
            return
        try:
            given = ContributionsIn.model_validate(body)
        except ValidationError as exc:
            self._warn(
                app, "contributions", f"contributions of {app} refused: {exc.errors()[0]['msg']}"
            )
            return
        text = self._json(given.model_dump(mode="json"))
        if self._contributed.get(app) == text:
            return
        self.contributions.put(app, given)
        self._contributed[app] = text

    def _declared(self, app: str, conditions: list[Any]) -> dict[str, dict[str, Any]]:
        specs = {spec.get("name"): spec for spec in self.events.catalog(app) or []}
        found: dict[str, dict[str, Any]] = {}
        for item in conditions:
            if not isinstance(item, dict):
                continue
            name, key = str(item.get("name") or ""), str(item.get("key") or "").strip()
            spec = specs.get(name)
            if spec is None or spec.get("phase") != "interval":
                self._warn(app, name, f"{app} reports {name!r}, not declared as an interval event")
                continue
            if key and key not in found:
                found[key] = {**item, "spec": spec}
        return found

    def _start(self, app: str, key: str, item: dict[str, Any]) -> None:
        spec = item["spec"]
        kind = f"{app}.{item['name']}"
        subject = self._subject(app, item.get("subject"))
        summary = str(item.get("summary") or spec.get("title") or kind)[:500]
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        severity = str(item.get("severity") or spec.get("severity") or "warning")
        self.events.publish(
            kind,
            subject,
            source=app,
            actor=ACTOR,
            summary=summary,
            payload=payload,
            refs=[str(ref) for ref in item.get("refs") or []],
            severity=severity,
            key=key,
            phase="start",
            category=str(spec.get("category") or ""),
        )
        owners = self._tell(app, key, subject, summary, payload, severity, spec)
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO relayed_conditions
                    (app, condition_key, kind, subject, summary, opened_at, owners)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (app, key, kind, subject, summary, self._now(), self._json(owners)),
            )

    def _end(self, app: str, key: str, row: dict[str, Any]) -> None:
        spec = next(
            (s for s in self.events.catalog(app) or [] if f"{app}.{s.get('name')}" == row["kind"]),
            {},
        )
        self.events.publish(
            row["kind"],
            row["subject"],
            source=app,
            actor=ACTOR,
            summary=row["summary"],
            payload={"opened_at": row["opened_at"]},
            severity="ok",
            key=key,
            phase="end",
            category=str(spec.get("category") or ""),
        )
        if self._loads(row.get("owners"), []) and self.notifications is not None:
            try:
                self.notifications().resolve(
                    app,
                    f"condition:{key}",
                    t("Back to normal at {moment}", moment=plant_clock(datetime.now(timezone.utc))),
                )
            except Exception:  # noqa: BLE001 - the event is written all the same
                LOGGER.exception("notification of %s/%s not settled", app, key)
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM relayed_conditions WHERE app = ? AND condition_key = ?", (app, key)
            )

    def _tell(
        self,
        app: str,
        key: str,
        subject: str,
        summary: str,
        payload: dict[str, Any],
        severity: str,
        spec: dict[str, Any],
    ) -> list[str]:
        """Notify the condition's ``owners`` (with an email); answers who was told."""

        owners = [
            str(ref).strip().lower()
            for ref in payload.get("owners") or []
            if str(ref).strip().lower().startswith(("user:", "group:"))
        ][:MAX_OWNERS]
        if not owners or self.notifications is None:
            return []
        lines = [str(spec.get("description") or "")]
        contact = " ".join(str(payload.get("contact") or "").split())[:300]
        if contact:
            lines.append(t("Contact: {contact}", contact=contact))
        name = (self.app_names() if self.app_names else {}).get(app, app)
        source = str(payload.get("source") or "")
        try:
            self.notifications().notify(
                app,
                name,
                recipients=owners,
                title=summary,
                text="\n\n".join(line for line in lines if line),
                priority=PRIORITIES.get(severity, "medium"),
                url=APP_PAGES[app].format(source=source) if source and app in APP_PAGES else None,
                email=True,
                refs=[subject],
                key=f"condition:{key}",
                category=str(spec.get("category") or "") or None,
            )
        except Exception:  # noqa: BLE001 - the event is written all the same
            LOGGER.exception("owners of %s/%s not told", app, key)
            return []
        return owners

    @staticmethod
    def _subject(app: str, subject: Any) -> str:
        if subject:
            try:
                return str(parse_ref(str(subject)))
            except ValueError:
                pass
        return f"app:{app}"

    def _warn(self, app: str, what: str, text: str) -> None:
        if (app, what) not in self._warned:
            self._warned.add((app, what))
            LOGGER.warning("conditions: %s", text)
