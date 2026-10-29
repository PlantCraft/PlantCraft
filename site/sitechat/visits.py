"""How many people read the site, and for how long, without cookies or addresses.

Each page view sends /api/visit when it opens (with a random id that lives in its tab only) and
again every 30 seconds while it is in front (page/assets/visit.js). A page view is kept as when it
opened, when it was last in front, the page, the site it came from (its host name only) and the
country Cloudflare names, and the buttons and links clicked (their words and where they go). People are told apart within one day by a hash of their address and
browser with a salt that lives in memory and changes every day, so the same person is two
visitors on two days, and no stored value leads back to an address (privacy.html).
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

ID = re.compile(r"^[a-z0-9]{6,40}$")
HOST = re.compile(r"^[a-z0-9.-]{1,100}$")
COUNTRY = re.compile(r"^[A-Z]{2}$")
# Not people: crawlers, link previews, headless browsers.
BOT = re.compile(r"bot|crawl|spider|slurp|preview|headless|lighthouse|curl|wget|python", re.I)
# A page view not heard from this long has been closed; one is never counted longer than LONGEST.
GONE_SECONDS = 600
LONGEST = 4 * 3600
# Page views one visitor opens in a day at most (a script cannot fill the table).
MAX_VIEWS_A_DAY = 300
KEEP_DAYS = 400

SCHEMA = """
CREATE TABLE IF NOT EXISTS views (
    id TEXT PRIMARY KEY,
    visitor TEXT NOT NULL,
    started REAL NOT NULL,
    last_seen REAL NOT NULL,
    page TEXT NOT NULL,
    referrer TEXT NOT NULL,
    country TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS views_started ON views (started);
CREATE TABLE IF NOT EXISTS clicks (
    id TEXT NOT NULL,
    label TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS clicks_at ON clicks (at);
"""
# Clicks one page view counts at most.
MAX_CLICKS = 100


class Visits:
    def __init__(self, folder: Path):
        self.path = folder / "visits.sqlite3"
        self._lock = threading.Lock()
        self._salt: tuple[int, bytes] = (-1, b"")
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as connection:
                connection.executescript(SCHEMA)
            self.path.chmod(0o600)
            self._ready = True
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _visitor(self, address: str, agent: str, now: float) -> str:
        day = int(now // 86400)
        if self._salt[0] != day:
            self._salt = (day, secrets.token_bytes(32))
        return hashlib.sha256(self._salt[1] + f"{address}\n{agent}".encode()).hexdigest()[:16]

    def hit(
        self,
        view: str,
        *,
        address: str,
        agent: str,
        page: str | None = None,
        referrer: str = "",
        country: str = "",
        click: str = "",
        now: float | None = None,
    ) -> None:
        """A page view opened (``page`` given), still in front (only its id), or a button or link
        clicked in it (``click``: its words and where it goes)."""

        now = time.time() if now is None else now
        if not ID.match(view) or BOT.search(agent or "") or not agent:
            return
        with self._lock, self._connect() as connection:
            if click and page is None:
                known = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM views WHERE id = ? AND started > ?), "
                    "(SELECT COUNT(*) FROM clicks WHERE id = ?)",
                    (view, now - LONGEST, view),
                ).fetchone()
                if known[0] and known[1] < MAX_CLICKS:
                    label = " ".join(click.split())[:200]
                    connection.execute(
                        "INSERT INTO clicks (id, label, at) VALUES (?, ?, ?)", (view, label, now)
                    )
                return
            if page is None:
                connection.execute(
                    "UPDATE views SET last_seen = ? WHERE id = ? AND last_seen > ? AND started > ?",
                    (now, view, now - GONE_SECONDS, now - LONGEST),
                )
                return
            visitor = self._visitor(address, agent, now)
            opened = connection.execute(
                "SELECT COUNT(*) FROM views WHERE visitor = ? AND started > ?",
                (visitor, now - 86400),
            ).fetchone()[0]
            if opened >= MAX_VIEWS_A_DAY:
                return
            page = page[:200] if page.startswith("/") else "/"
            referrer = referrer.lower()[:100]
            connection.execute(
                "INSERT OR IGNORE INTO views (id, visitor, started, last_seen, page, referrer, "
                "country) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    view,
                    visitor,
                    now,
                    now,
                    page,
                    referrer if HOST.match(referrer) else "",
                    country if COUNTRY.match(country or "") else "",
                ),
            )
            if secrets.randbelow(200) == 0:
                connection.execute(
                    "DELETE FROM views WHERE started < ?", (now - KEEP_DAYS * 86400,)
                )
                connection.execute("DELETE FROM clicks WHERE at < ?", (now - KEEP_DAYS * 86400,))

    def since(self, start: float) -> list[sqlite3.Row]:
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT id, visitor, started, last_seen, page, referrer, country FROM views "
                "WHERE started >= ? ORDER BY started",
                (start,),
            ).fetchall()

    def clicks(self, start: float, limit: int = 20) -> list[tuple[str, int]]:
        """The buttons and links clicked since ``start``, by how many page views clicked each."""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT label, COUNT(DISTINCT id) AS n FROM clicks WHERE at >= ? GROUP BY label "
                "ORDER BY n DESC, label LIMIT ?",
                (start, limit),
            ).fetchall()
        return [(row["label"], int(row["n"])) for row in rows]

    def clicked(self, start: float) -> list[sqlite3.Row]:
        """Every click since ``start``, oldest first (``id`` is the page view's)."""
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT id, label, at FROM clicks WHERE at >= ? ORDER BY at", (start,)
            ).fetchall()
