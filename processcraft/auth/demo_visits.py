"""Visits of a public demo: a few places at once, and a line to wait in when they are all taken.

"Enter the demo" (``POST /api/demo/enter``) takes a free place, or puts the browser in line with
a ticket it shows again every few seconds; whoever is first in line takes the next place that
frees. A visit lasts while it is used: each sign of use (``POST /api/demo/heartbeat`` with
``active``) moves its end ``minutes`` ahead, so it ends ``minutes`` after its last use, or when its
visitor signs out. A visitor unused for ``idle_minutes`` gives up their place, but only to someone
waiting. No cap per address: behind the demo's proxy and tunnel, every visitor can seem to come
from one (owner, 2026-10-28: that locked visitors out).

In the database, not in memory, so every server process sees the same places. Every visit is
the same read-only visitor account: the place is what is counted, not the person.

The demo's guides by role (``frontend/src/demoGuides.tsx``) point at what the demo story holds by
name ("Plant overview", "DOC-MH-001"); ``processcraft demo seed`` writes here the page each name
opens (``demo_guide_links``), since the apps give their objects new ids on every installation.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from processcraft.db import Database, Store

# A ticket whose browser stopped asking for this long has left the line.
LINE_GONE_SECONDS = 30.0


@dataclass(frozen=True)
class Visit:
    visit: str
    started: float
    ends: float

    def seconds_left(self, now: float | None = None) -> int:
        return max(int(self.ends - (time.time() if now is None else now)), 0)


@dataclass(frozen=True)
class Waiting:
    ticket: str
    # 1 for the first in line.
    position: int
    # About how long until a place is theirs.
    wait_seconds: int


class DemoVisits(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS demo_visits (
        visit TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        started REAL NOT NULL,
        ends REAL NOT NULL,
        active REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS demo_line (
        ticket TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        joined REAL NOT NULL,
        seen REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS demo_guide_links (
        name TEXT PRIMARY KEY,
        href TEXT NOT NULL
    );
    """

    def __init__(self, db: Database):
        super().__init__(db)

    def enter(
        self,
        *,
        seats: int,
        minutes: float,
        idle_minutes: float,
        address: str,
        ticket: str | None = None,
        now: float | None = None,
    ) -> Visit | Waiting:
        """A place for this browser, or its place in line (``ticket`` from its last answer)."""

        now = time.time() if now is None else now
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM demo_visits WHERE ends <= ?", (now,))
            connection.execute("DELETE FROM demo_line WHERE seen < ?", (now - LINE_GONE_SECONDS,))
            visits = connection.execute(
                "SELECT visit, address, ends, active FROM demo_visits ORDER BY active"
            ).fetchall()
            known = (
                ticket
                and connection.execute(
                    "SELECT 1 FROM demo_line WHERE ticket = ?", (ticket,)
                ).fetchone()
            )
            if known:
                connection.execute("UPDATE demo_line SET seen = ? WHERE ticket = ?", (now, ticket))
            else:
                ticket = secrets.token_urlsafe(18)
                connection.execute(
                    "INSERT INTO demo_line (ticket, address, joined, seen) VALUES (?, ?, ?, ?)",
                    (ticket, address, now, now),
                )
            line = [
                row["ticket"]
                for row in connection.execute(
                    "SELECT ticket FROM demo_line ORDER BY joined, ticket"
                )
            ]
            position = line.index(ticket)
            free = seats - len(visits)
            if position >= free:
                # Someone waits: the places of visitors idle the longest go to the line.
                idle = [row["visit"] for row in visits if row["active"] < now - idle_minutes * 60]
                taken = idle[: max(position + 1 - free, 0)]
                connection.executemany(
                    "DELETE FROM demo_visits WHERE visit = ?", [(visit,) for visit in taken]
                )
                free += len(taken)
                visits = [row for row in visits if row["visit"] not in taken]
            if position < free:
                visit = Visit(secrets.token_urlsafe(18), now, now + minutes * 60)
                connection.execute("DELETE FROM demo_line WHERE ticket = ?", (ticket,))
                connection.execute(
                    """
                    INSERT INTO demo_visits (visit, address, started, ends, active)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (visit.visit, address, visit.started, visit.ends, now),
                )
                return visit
            # About when the place they wait for frees: the visits ending first, one per person
            # ahead of them, else a whole visit.
            ending = sorted(row["ends"] - now for row in visits)
            ahead = max(position - max(free, 0), 0)
            wait = ending[ahead] if ahead < len(ending) else minutes * 60
            return Waiting(ticket, position + 1, max(int(wait), 1))

    def get(self, visit: str | None, now: float | None = None) -> Visit | None:
        """The visit while it lasts; None once it ended or gave its place up."""

        if not visit:
            return None
        now = time.time() if now is None else now
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT visit, started, ends FROM demo_visits WHERE visit = ? AND ends > ?",
                (visit, now),
            ).fetchone()
        return Visit(row["visit"], row["started"], row["ends"]) if row else None

    def seen(
        self, visit: str, *, active: bool, minutes: float, now: float | None = None
    ) -> Visit | None:
        """A sign of life from the visit's browser; ``active`` when the visitor used it, which
        moves the visit's end ``minutes`` ahead."""

        now = time.time() if now is None else now
        if active:
            with self._lock, self._write() as connection:
                connection.execute(
                    "UPDATE demo_visits SET active = ?, ends = ? WHERE visit = ? AND ends > ?",
                    (now, now + minutes * 60, visit, now),
                )
        return self.get(visit, now)

    def leave(self, visit: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM demo_visits WHERE visit = ?", (visit,))

    def counts(self, now: float | None = None) -> dict[str, int]:
        """Places taken and people waiting now."""

        now = time.time() if now is None else now
        with self._lock, self._connect() as connection:
            taken = connection.execute(
                "SELECT COUNT(*) FROM demo_visits WHERE ends > ?", (now,)
            ).fetchone()[0]
            waiting = connection.execute(
                "SELECT COUNT(*) FROM demo_line WHERE seen >= ?", (now - LINE_GONE_SECONDS,)
            ).fetchone()[0]
        return {"taken": int(taken), "waiting": int(waiting)}

    def set_guide_links(self, links: dict[str, str]) -> None:
        """The pages the demo story's names open now (all of them: the old ones are dropped)."""

        rows = [
            (str(name)[:200], href)
            for name, href in links.items()
            if isinstance(href, str) and href.startswith("/") and not href.startswith("//")
        ]
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM demo_guide_links")
            connection.executemany(
                "INSERT OR REPLACE INTO demo_guide_links (name, href) VALUES (?, ?)", rows
            )

    def guide_links(self) -> dict[str, str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT name, href FROM demo_guide_links ORDER BY name")
            return {row["name"]: row["href"] for row in rows}
