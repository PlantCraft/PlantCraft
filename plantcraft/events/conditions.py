"""The conditions an app reports in its metrics, written as that app's events.

The Historian answers the suite and never calls it: it has no app key, so it cannot post events.
It names the conditions it has open now in ``GET /api/ops/metrics`` instead
(``plantcraft_sdk.server.ops.report_conditions``), with its event catalog. Each minute the
health recorder (``plantcraft.watch.recorder``) reads every server's metrics and hands them
here: the relay keeps the app's catalog, compares the conditions with the ones the app reported
before and writes, in the app's name, a ``start`` for each new one and an ``end`` for each one
gone. Alarms then judges them like any other event.

An app that did not answer this minute keeps its conditions open: not knowing is not good news,
and the suite watch already says the app is down. Open conditions are stored, so a restart
neither repeats a start nor forgets an end. A condition whose name the app does not declare as
an ``interval`` event is left out and logged once.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from plantcraft.db import Store
from plantcraft.refs import parse_ref
from plantcraft_sdk.contributes import ContributionsIn
from plantcraft_sdk.events import CatalogIn

LOGGER = logging.getLogger(__name__)

ACTOR = "system"


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

    def __init__(self, db: Any, events: Any, contributions: Any = None):
        super().__init__(db)
        self.events = events
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
        self.events.publish(
            kind,
            subject,
            source=app,
            actor=ACTOR,
            summary=summary,
            payload=item.get("payload") if isinstance(item.get("payload"), dict) else {},
            refs=[str(ref) for ref in item.get("refs") or []],
            severity=str(item.get("severity") or spec.get("severity") or "warning"),
            key=key,
            phase="start",
            category=str(spec.get("category") or ""),
        )
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO relayed_conditions
                    (app, condition_key, kind, subject, summary, opened_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (app, key, kind, subject, summary, self._now()),
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
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM relayed_conditions WHERE app = ? AND condition_key = ?", (app, key)
            )

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
