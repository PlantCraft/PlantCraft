"""Limits that keep a public chat cheap and safe: requests per address, a daily budget, sizes."""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque

MAX_MESSAGE = 1200  # characters in one visitor message
MAX_TURNS = 12  # messages of history sent with a question
MAX_HISTORY = 9000  # characters of history in all

# Anything that looks like a price, in the currencies a visitor may ask in. The chat never
# quotes one (the site has none); an answer that has one is replaced, whatever the model wrote.
PRICE = re.compile(
    r"(R\$|US\$|U\$|€|£|\bUSD\b|\bEUR\b|\bBRL\b|\$\s?\d"
    r"|\d[\d.,]*\s?(k|mil|thousand|million|milh[õo]es)?\s?(reais|dollars?|d[oó]lares|euros?)\b)",
    re.I,
)


class Window:
    """At most `limit` events per key in the last `seconds`."""

    def __init__(self, limit: int, seconds: float):
        self.limit = limit
        self.seconds = seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self.seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            if len(self._events) > 50_000:  # forget idle addresses
                for k in [k for k, v in self._events.items() if not v]:
                    del self._events[k]
            return True


class Limits:
    """The chat's and the contact form's limits, per visitor address and for the whole site."""

    def __init__(self, daily_answers: int = 1000):
        self.chat_minute = Window(8, 60)
        self.chat_day = Window(60, 86_400)
        self.answers_day = Window(daily_answers, 86_400)
        self.contact_hour = Window(3, 3_600)

    def chat(self, address: str) -> str | None:
        """None when this question may go to the model, else why not."""
        if not self.chat_minute.allow(address):
            return "minute"
        if not self.chat_day.allow(address):
            return "day"
        if not self.answers_day.allow("site"):
            return "budget"
        return None

    def contact(self, address: str) -> bool:
        return self.contact_hour.allow(address)


def has_price(text: str) -> bool:
    return bool(PRICE.search(text))
