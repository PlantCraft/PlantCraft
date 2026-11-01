"""Visits of a public demo: a few places at once, and a line to wait in when they are all taken.

"Enter the demo" (``POST /api/demo/enter``) takes a free place, or puts the browser in line with
a ticket it shows again every few seconds; whoever is first in line takes the next place that
frees. A visit lasts ``minutes`` at most from its start (the clock the visitor sees), and ends
sooner when its visitor leaves it unused for ``idle_minutes``: each sign of use
(``POST /api/demo/heartbeat`` with ``active``) moves that idle end ahead, never past the clock.
``ends`` in the table is the earlier of the two. No cap per address: behind the demo's proxy and tunnel, every visitor can seem to come
from one (that locked visitors out).

In the database, not in memory, so every server process sees the same places. Every visit is
the same read-only visitor account: the place is what is counted, not the person.

Each visit also leaves a line in ``demo_visit_log`` (when it started, how long it was used, how
long its visitor waited in line; no address), so the owner can see how many people visit and for
how long (``GET /api/demo/stats``). The lines are kept ``LOG_DAYS``.

The demo's guides by role (``frontend/src/demoGuides.tsx``) point at what the demo story holds by
name ("Plant overview", "DOC-MH-001"); ``processcraft demo seed`` writes here the page each name
opens (``demo_guide_links``), since the apps give their objects new ids on every installation.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass

from plantcraft.db import Database, Store

# An update notice nobody cleared is forgotten this long after the update was due.
NOTICE_STALE_SECONDS = 30 * 60
# A ticket whose browser stopped asking for this long has left the line.
LINE_GONE_SECONDS = 30.0
# Days the log of past visits keeps.
LOG_DAYS = 400
# A path segment that is an object's id ("/link/runs/8f3a..."), counted as one page.
ID_SEGMENT = re.compile(r"^(\d+|[0-9a-f-]{8,}|[A-Za-z0-9_-]{20,})$")


@dataclass(frozen=True)
class Visit:
    visit: str
    started: float
    # The earlier of the visit's clock and its idle end.
    ends: float

    def seconds_left(self, now: float | None = None) -> int:
        return max(int(self.ends - (time.time() if now is None else now)), 0)

    def clock_left(self, minutes: float, now: float | None = None) -> int:
        """Seconds left on the visit's clock (``minutes`` from its start), use or not."""

        return max(int(self.started + minutes * 60 - (time.time() if now is None else now)), 0)


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

    CREATE TABLE IF NOT EXISTS demo_visit_log (
        visit TEXT PRIMARY KEY,
        started REAL NOT NULL,
        last_used REAL NOT NULL,
        waited REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS demo_visit_log_started ON demo_visit_log (started);

    CREATE TABLE IF NOT EXISTS demo_visit_pages (
        visit TEXT NOT NULL,
        page TEXT NOT NULL,
        at REAL NOT NULL,
        PRIMARY KEY (visit, page)
    );

    CREATE TABLE IF NOT EXISTS demo_update_notice (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        at REAL NOT NULL
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
                visit = Visit(secrets.token_urlsafe(18), now, now + min(minutes, idle_minutes) * 60)
                joined = connection.execute(
                    "SELECT joined FROM demo_line WHERE ticket = ?", (ticket,)
                ).fetchone()
                connection.execute("DELETE FROM demo_line WHERE ticket = ?", (ticket,))
                connection.execute(
                    "DELETE FROM demo_visit_pages WHERE visit IN (SELECT visit FROM "
                    "demo_visit_log WHERE started < ?)",
                    (now - LOG_DAYS * 86400,),
                )
                connection.execute(
                    "DELETE FROM demo_visit_log WHERE started < ?", (now - LOG_DAYS * 86400,)
                )
                connection.execute(
                    "INSERT INTO demo_visit_log (visit, started, last_used, waited) "
                    "VALUES (?, ?, ?, ?)",
                    (visit.visit, now, now, max(now - joined["joined"], 0) if joined else 0),
                )
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
        self,
        visit: str,
        *,
        active: bool,
        minutes: float,
        idle_minutes: float,
        now: float | None = None,
    ) -> Visit | None:
        """A sign of life from the visit's browser; ``active`` when the visitor used it, which
        moves the visit's end ``idle_minutes`` ahead, never past its clock (``minutes`` from its
        start)."""

        now = time.time() if now is None else now
        if active:
            with self._lock, self._write() as connection:
                connection.execute(
                    "UPDATE demo_visits SET active = ?, ends = MIN(started + ?, ?) "
                    "WHERE visit = ? AND ends > ?",
                    (now, minutes * 60, now + idle_minutes * 60, visit, now),
                )
                connection.execute(
                    "UPDATE demo_visit_log SET last_used = ? WHERE visit = ? AND last_used < ?",
                    (now, visit, now),
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

    def history(self, since: float, now: float | None = None) -> list[dict[str, float]]:
        """The visits started since ``since``, oldest first: when each started, how long it was
        used (seconds from its start to its last use) and how long its visitor waited first."""

        now = time.time() if now is None else now
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT started, last_used, waited FROM demo_visit_log WHERE started >= ? "
                "ORDER BY started LIMIT 50000",
                (since,),
            ).fetchall()
        return [
            {
                "started": row["started"],
                "seconds": round(max(min(row["last_used"], now) - row["started"], 0)),
                "waited": round(row["waited"]),
            }
            for row in rows
        ]

    def opened(self, visit: str, paths: list[str], now: float | None = None) -> None:
        """The pages a visit had in front, in the order it had them (paths only; an object's id
        counts as ``:id``); each page keeps when the visit first opened it."""

        now = time.time() if now is None else now
        pages: dict[str, None] = {}
        for path in paths[:20]:
            if not isinstance(path, str) or not path.startswith("/"):
                continue
            parts = [":id" if ID_SEGMENT.match(p) else p for p in path[:200].split("/") if p]
            pages["/" + "/".join(parts[:6])] = None
        if not pages:
            return
        with self._lock, self._write() as connection:
            if not connection.execute(
                "SELECT 1 FROM demo_visit_log WHERE visit = ?", (visit,)
            ).fetchone():
                return
            known = connection.execute(
                "SELECT COUNT(*) FROM demo_visit_pages WHERE visit = ?", (visit,)
            ).fetchone()[0]
            connection.executemany(
                "INSERT OR IGNORE INTO demo_visit_pages (visit, page, at) VALUES (?, ?, ?)",
                [(visit, page, now) for page in pages][: max(200 - known, 0)],
            )

    def pages(self, since: float, limit: int = 30) -> list[dict[str, object]]:
        """The pages the visits started since ``since`` opened, by how many visits opened each."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT p.page, COUNT(*) AS visits FROM demo_visit_pages p JOIN demo_visit_log l "
                "ON l.visit = p.visit WHERE l.started >= ? GROUP BY p.page "
                "ORDER BY visits DESC, p.page LIMIT ?",
                (since, limit),
            ).fetchall()
        return [{"page": row["page"], "visits": int(row["visits"])} for row in rows]

    def journeys(self, since: float, limit: int = 300, now: float | None = None) -> list[dict]:
        """The last ``limit`` visits started since ``since``, newest first, each with the pages it
        opened in order (seconds after its start). A visit is named by a short code, never by
        what signs it in."""

        now = time.time() if now is None else now
        with self._lock, self._connect() as connection:
            visits = connection.execute(
                "SELECT visit, started, last_used, waited FROM demo_visit_log WHERE started >= ? "
                "ORDER BY started DESC LIMIT ?",
                (since, limit),
            ).fetchall()
            pages: dict[str, list] = {}
            for row in connection.execute(
                "SELECT visit, page, at FROM demo_visit_pages WHERE visit IN "
                "(SELECT visit FROM demo_visit_log WHERE started >= ? ORDER BY started DESC "
                "LIMIT ?) ORDER BY at, rowid",
                (since, limit),
            ):
                pages.setdefault(row["visit"], []).append(row)
        return [
            {
                "visitor": hashlib.sha256(v["visit"].encode()).hexdigest()[:8],
                "started": v["started"],
                "seconds": round(max(min(v["last_used"], now) - v["started"], 0)),
                "waited": round(v["waited"]),
                "pages": [
                    [p["page"], round(max(p["at"] - v["started"], 0))]
                    for p in pages.get(v["visit"], [])
                ],
            }
            for v in visits
        ]

    def announce_update(self, at: float) -> None:
        """The demo will be updated (and stopped a while) at ``at``: visits see a countdown, no new
        visit starts, and when it comes every visit ends (``plantcraft demo update-notice``)."""

        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO demo_update_notice (id, at) VALUES (1, ?) "
                "ON CONFLICT (id) DO UPDATE SET at = excluded.at",
                (at,),
            )

    def clear_update(self) -> None:
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM demo_update_notice")

    def update_at(self, now: float | None = None) -> float | None:
        """When the announced update stops the demo, or None (none announced, or one long past
        that nobody cleared)."""

        now = time.time() if now is None else now
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT at FROM demo_update_notice WHERE id = 1").fetchone()
        if row is None or row["at"] + NOTICE_STALE_SECONDS < now:
            return None
        return float(row["at"])

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
