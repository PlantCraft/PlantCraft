"""Public demo mode: an installation left open on the internet for visitors to try.

``PLANTCRAFT_PUBLIC_DEMO=true`` (``install.sh --public-demo``) turns it on:

- the sign-in page offers "Enter the demo": a visit of the visitor account
  (``PLANTCRAFT_PUBLIC_DEMO_USER``, default ``demo``, made read-only by ``processcraft demo
  seed``) in one of a few places at once, for as long as it is used, with a line to wait in when
  every place is taken (``processcraft.auth.demo_visits``, docs/public-demo.md). From outside, through
  the proxy, the visitor account signs in only that way, never with its password
  (``PLANTCRAFT_PUBLIC_DEMO_PASSWORD``, which ``processcraft demo seed`` still uses inside);
- viewers (the visitor account) are read-only in PlantCraft, conversations included, so a
  visitor cannot write anything another visitor would read; editors and administrators are
  people the administrator created on purpose (the demo's cast has random passwords);
- language models are only for the people an administrator created (editors and
  administrators): visitors never reach one, and neither do the apps' uses;
- each client address gets at most ``PLANTCRAFT_PUBLIC_DEMO_RATE`` requests per minute
  (default 600) before a 429.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from plantcraft_sdk.server.settings import env_flag

DEFAULT_USER = "demo"
DEFAULT_RATE = 600
DEFAULT_SEATS = 10
# A visit unused this long ends (owner, 2026-10-28: no clock while it is used; a tab forgotten for
# days must not hold a place).
DEFAULT_MINUTES = 30
DEFAULT_IDLE_MINUTES = 5
# Requests a visitor's browser has in flight in each app at once, and all visitors together.
DEFAULT_QUERIES = 4
DEFAULT_QUERIES_TOTAL = 8
WINDOW_SECONDS = 60.0
# Addresses kept in memory at most; the oldest are forgotten first.
MAX_CLIENTS = 20000


@dataclass(frozen=True)
class PublicDemo:
    username: str
    password: str
    rate_per_minute: int
    # Places for visits at once, after how long unused a visit ends, and after how long unused a
    # visitor gives up their place to someone waiting.
    seats: int = DEFAULT_SEATS
    minutes: int = DEFAULT_MINUTES
    idle_minutes: int = DEFAULT_IDLE_MINUTES
    queries: int = DEFAULT_QUERIES
    queries_total: int = DEFAULT_QUERIES_TOTAL

    def as_dict(self) -> dict[str, int]:
        """What the sign-in page says about the demo (never the visitor's password)."""

        return {"seats": self.seats, "minutes": self.minutes}

    def token_claim(self, visit: str, ends: float) -> dict[str, object]:
        """The ``demo`` claim of a visit's tokens: the apps show their editors (nothing saves)
        and hold the visitor's requests to ``queries`` at once (``plantcraft_sdk.auth``)."""

        return {
            "visit": visit,
            "ends": int(ends),
            "queries": self.queries,
            "queries_total": self.queries_total,
        }


def _number(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        value = default
    return min(max(value, low), high)


def public_demo() -> PublicDemo | None:
    """The public demo's settings, or None when the installation is not a public demo."""

    if not env_flag("PLANTCRAFT_PUBLIC_DEMO"):
        return None
    return PublicDemo(
        username=os.environ.get("PLANTCRAFT_PUBLIC_DEMO_USER", DEFAULT_USER).strip().lower()
        or DEFAULT_USER,
        password=os.environ.get("PLANTCRAFT_PUBLIC_DEMO_PASSWORD", "").strip(),
        rate_per_minute=_number("PLANTCRAFT_PUBLIC_DEMO_RATE", DEFAULT_RATE, 1, 1_000_000),
        seats=_number("PLANTCRAFT_PUBLIC_DEMO_SEATS", DEFAULT_SEATS, 1, 500),
        minutes=_number("PLANTCRAFT_PUBLIC_DEMO_MINUTES", DEFAULT_MINUTES, 1, 24 * 60),
        idle_minutes=_number("PLANTCRAFT_PUBLIC_DEMO_IDLE_MINUTES", DEFAULT_IDLE_MINUTES, 1, 600),
        queries=_number("PLANTCRAFT_PUBLIC_DEMO_QUERIES", DEFAULT_QUERIES, 1, 32),
        queries_total=_number(
            "PLANTCRAFT_PUBLIC_DEMO_QUERIES_TOTAL", DEFAULT_QUERIES_TOTAL, 1, 512
        ),
    )


class RateLimiter:
    """Sliding one-minute window per client address, in memory (one process)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.pop(client, None) or deque()
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            allowed = len(hits) < self.per_minute
            if allowed:
                hits.append(now)
            # Re-inserted last, so the dict keeps the most recent clients at the end.
            self._hits[client] = hits
            while len(self._hits) > MAX_CLIENTS:
                self._hits.pop(next(iter(self._hits)))
            return allowed
