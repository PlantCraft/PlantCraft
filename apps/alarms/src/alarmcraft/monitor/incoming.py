"""Reading what the apps report: each cycle, the events published in PlantCraft since the last
one (``GET /api/v1/events`` after the last id read). The cycle's rules read them (their event
blocks), then they are kept in ``IncomingStore`` with the rules they counted for, and the
conditions they open or end are kept up to date.

The first read starts at the newest event: Alarms judges what happens from then on, not the
suite's whole past (the last day's events are only shown in Events, to start rules from). A
read that fails leaves the mark where it was, so the next cycle catches up.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.client import PlantCraftError

from alarmcraft import APP_ID
from alarmcraft.alarms.incoming import IncomingStore, severity_of
from alarmcraft.alarms.rules import RuleStore
from alarmcraft.i18n import t

LOGGER = logging.getLogger(__name__)
MARK = "events_after"
PAGE = 500
# At most this many pages a cycle; the rest waits for the next one.
PAGES = 10
# The first read shows the events of the last day in Events (counted by no rule).
FIRST_LOOK = timedelta(days=1)


def _time(text: Any, fallback: datetime) -> datetime:
    try:
        moment = datetime.fromisoformat(str(text))
    except ValueError:
        return fallback
    return moment if moment.tzinfo else moment.replace(tzinfo=fallback.tzinfo)


def owner_of(event: dict[str, Any]) -> str | None:
    """The owner an app names in its event (Link: the execution's), else None."""

    return str((event.get("payload") or {}).get("owner") or "") or None


class Incoming:
    def __init__(
        self,
        rules: RuleStore,
        store: IncomingStore,
        client: Any | None,
        *,
        clock: Callable[[], datetime],
    ):
        self.rules = rules
        self.store = store
        self.client = client
        self.clock = clock
        self.last_error = ""
        self.read_count = 0

    def _fetch(self) -> list[dict[str, Any]]:
        mark = self.rules.meta(MARK)
        if mark is None:
            # The latest events of the last day are shown in Events (to start rules from), but
            # counted by no rule.
            latest = list(self.client.events(limit=PAGE))
            self.rules.set_meta(MARK, str(latest[-1]["id"] if latest else 0))
            now = self.clock()
            since = now - FIRST_LOOK
            shown = [
                item
                for item in latest
                if item.get("app") != APP_ID and _time(item.get("at"), now) >= since
            ]
            if shown:
                self.store.add(shown, {}, now=now)
            return []
        after = int(mark)
        found: list[dict[str, Any]] = []
        for _ in range(PAGES):
            page = list(self.client.events(after=after, limit=PAGE))
            if not page:
                break
            found.extend(page)
            after = int(page[-1]["id"])
            if len(page) < PAGE:
                break
        if found:
            self.rules.set_meta(MARK, str(after))
        return found

    def read(self) -> list[dict[str, Any]]:
        """The events other apps published since the last read, oldest first."""

        if self.client is None:
            return []
        try:
            events = [item for item in self._fetch() if item.get("app") != APP_ID]
        except (PlantCraftError, ValueError, TypeError, KeyError) as exc:
            self.last_error = t("events: {why}", why=exc)[:300]
            LOGGER.warning("Events not read: %s", exc)
            return []
        self.last_error = ""
        for event in events:
            event["severity"] = severity_of(event) or event.get("severity") or ""
        return events

    def keep(
        self, events: list[dict[str, Any]], counted: dict[int, list[str]], now: datetime
    ) -> None:
        """Keep the events read, with the rules each counted for (event id → rule ids)."""

        if events:
            self.store.add(events, counted, now=now)
            self.read_count += len(events)
