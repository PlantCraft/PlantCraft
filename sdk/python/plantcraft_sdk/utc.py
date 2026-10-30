"""Every time in UTC: one text form for every instant the suite stores or answers.

``2026-10-23T14:05:09.123Z``: UTC, milliseconds, fixed width. Two of them compare as text in
their time order, so SQL filters and sorts them as plain text. Each person sees them in their own
time zone: converting is the interface's job, never the database's.

``normalize_times`` rewrites, once, the instants a database stored in an older form (the server's
local offset, ``...-03:00``, or ``+00:00``), whose text order is not their time order.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOGGER = logging.getLogger(__name__)
_INSTANT = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:?\d{2})?$"
)


def utc_iso(value: datetime | str | None = None) -> str:
    """``value`` (now without it) as ``2026-10-23T14:05:09.123Z``.

    A datetime or an ISO 8601 text; a time without an offset is UTC. Raises ValueError for a
    text that is not ISO 8601.
    """

    if value is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(value, str):
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        moment = value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_instant(value: object) -> datetime | None:
    """An ISO 8601 text (or a datetime) as an aware datetime; a time without an offset is UTC.

    None for an empty or unreadable value: the callers that must refuse one check for None.
    """

    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


LOCAL = "local"


def resolve_zone(name: str | None, local: str = "UTC") -> ZoneInfo:
    """The zone a saved setting means: ``local`` (or nothing, or a name this
    server does not know) is the installation's, ``local`` here (from
    ``PlantCraftClient.installation_time_zone()``); ``Etc/GMT+3`` is UTC−3. Saving ``local``
    keeps a schedule on the installation's clock when the installation's zone changes."""

    for candidate in ((name or "").strip(), (local or "").strip(), "UTC"):
        if not candidate or candidate == LOCAL:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


_installation: Callable[[], str] = lambda: "UTC"  # noqa: E731


def use_installation_zone(source: Callable[[], str]) -> None:
    """Where an app reads the installation's zone (its PlantCraft client's
    ``installation_time_zone``, set by the app's runtime): what ``local`` means."""

    global _installation
    _installation = source


def installation_zone() -> str:
    """The installation's IANA zone; UTC while PlantCraft cannot be read (the app keeps running)."""

    try:
        return _installation() or "UTC"
    except Exception:  # PlantCraft away: clocks keep running, on UTC
        LOGGER.warning("The installation's time zone could not be read; using UTC")
        return "UTC"


def zone_of(name: str | None) -> ZoneInfo:
    """The clock a saved zone means: ``local`` (or nothing) is the installation's, read through
    ``use_installation_zone``; a name this server does not know is the installation's too."""

    local = installation_zone()
    if not name or name.strip() == LOCAL:
        return resolve_zone(LOCAL, local)
    return resolve_zone(name, local)


def local_text(value: object, form: str = "%Y-%m-%d %H:%M", zone: str | None = None) -> str:
    """An instant (ISO text or datetime; no offset is UTC) as text on the installation's wall
    clock, or ``zone``'s: what a message, a notification or a document shows a person (owner,
    2026-10-27: every time in the user's time zone). Empty or unreadable: "—"."""

    moment = parse_instant(value)
    if moment is None:
        return "—"
    return moment.astimezone(zone_of(zone)).strftime(form)


def is_instant(value: object) -> bool:
    """A text holding a date and a time (a date alone is a day, not an instant)."""

    return isinstance(value, str) and bool(_INSTANT.match(value.strip()))


def time_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    """The columns of ``table`` that hold instants by the suite's naming: ``at`` and ``*_at``."""

    return [
        row[1]
        for row in connection.execute(f'PRAGMA table_info("{table}")')
        if row[1] == "at" or str(row[1]).endswith("_at")
    ]


def normalize_times(connection: sqlite3.Connection) -> int:
    """Rewrite every instant in ``at`` and ``*_at`` columns as ``utc_iso``; returns how many.

    Run inside the caller's transaction. Texts that are not instants (a date, a word) and those
    already in the form are left alone, so running it again changes nothing.
    """

    changed = 0
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        for column in time_columns(connection, table):
            try:
                rows = connection.execute(
                    f'SELECT rowid, "{column}" FROM "{table}" WHERE typeof("{column}") = \'text\''
                ).fetchall()
            except sqlite3.OperationalError:  # a table WITHOUT ROWID: none in the suite
                continue
            for rowid, value in rows:
                if not is_instant(value):
                    continue
                try:
                    fixed = utc_iso(value)
                except ValueError:
                    continue
                if fixed != value:
                    connection.execute(
                        f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ?', (fixed, rowid)
                    )
                    changed += 1
    return changed
