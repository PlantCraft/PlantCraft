"""The assistant for a public demo's visitors (``PLANTCRAFT_PUBLIC_DEMO_LLM``, docs/public-demo.md).

Off by default: a visitor reads the team's recorded chats and never reaches a model. Turned on
(``PLANTCRAFT_PUBLIC_DEMO_LLM=on`` beside ``PLANTCRAFT_PUBLIC_DEMO``), each visit asks the
installation's assistant model, under limits that keep a demo open on the internet cheap and
safe:

- **Its own chats.** A visit's chats belong to ``<visitor>#visit:<id>`` (``VISIT_OWNER``), not to
  the visitor account every visit shares: the next visitor never reads them. They are deleted
  ``keep_days`` after their last message (kept that long to read what visitors asked).
- **A few questions.** ``questions`` per visit, ``per_minute`` and ``per_address`` a day per
  client address, and ``daily`` for all visits together each plant day, counted in
  ``assistant_demo_questions`` (``DemoQuestions``), so a restart does not reset them; each row
  keeps the tokens its answer spent, which the demo's stats add up.
- **Short.** A question of ``max_text`` characters at most, the last ``history`` turns of the
  chat, ``rounds`` rounds and ``tool_calls`` tool calls per answer, ``reads`` signal reads per
  visit, and an answer of ``max_answer`` characters.
- **Nothing that leaves the suite.** An answer's images, raw HTML and links or addresses outside
  the suite are taken out on the server (``clean_answer``), whatever the model was led to write
  (a planted instruction in the plant's data or in the page's context).
- **Asks only.** No cards that create, no specialists, no works that create: the assistant reads
  and explains (``ChatEngine`` drops the create tools of a visit's chat too).

``PLANTCRAFT_PUBLIC_DEMO_LLM=off`` and a restart of PlantCraft turn it off again at once.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime

from plantcraft.auth.public_demo import VISIT_OWNER, public_demo
from plantcraft.config import plant_timezone
from plantcraft.db import Store, utc_text
from plantcraft.i18n import t
from plantcraft_sdk.server.settings import env_flag


@dataclass(frozen=True)
class DemoAssistant:
    """The limits of the assistant in a public demo's visits (each a ``PLANTCRAFT_PUBLIC_DEMO_LLM_*``
    setting)."""

    questions: int = 10
    per_minute: int = 6
    per_address: int = 30
    daily: int = 600
    max_text: int = 1200
    rounds: int = 4
    reads: int = 200
    keep_days: int = 7
    history: int = 12
    tool_calls: int = 16
    max_answer: int = 4000

    def as_dict(self) -> dict[str, int]:
        return {"questions": self.questions, "max_text": self.max_text}


def _number(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(f"PLANTCRAFT_PUBLIC_DEMO_LLM_{name}", default))
    except ValueError:
        value = default
    return min(max(value, low), high)


def demo_assistant() -> DemoAssistant | None:
    """The demo assistant's limits when this is a public demo whose visitors may ask the model,
    else None."""

    if public_demo() is None or not env_flag("PLANTCRAFT_PUBLIC_DEMO_LLM"):
        return None
    return DemoAssistant(
        questions=_number("QUESTIONS", 10, 1, 200),
        per_minute=_number("PER_MINUTE", 6, 1, 120),
        per_address=_number("PER_ADDRESS", 30, 1, 5_000),
        daily=_number("DAILY", 600, 1, 1_000_000),
        max_text=_number("MAX_TEXT", 1200, 50, 8000),
        rounds=_number("ROUNDS", 4, 0, 8),
        reads=_number("READS", 200, 1, 100_000),
        keep_days=_number("KEEP_DAYS", 7, 0, 90),
        history=_number("HISTORY", 12, 2, 30),
        tool_calls=_number("TOOL_CALLS", 16, 1, 64),
        max_answer=_number("MAX_ANSWER", 4000, 200, 32_000),
    )


_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_EXTERNAL_LINK = re.compile(r"\[([^\]]+)\]\(\s*(?:[a-z][a-z0-9+.-]*:|//)[^)]*\)", re.I)
_HTML = re.compile(r"</?[a-zA-Z][^>]*>")
_ADDRESS = re.compile(r"\b(?:https?|ftp)://\S+|\bwww\.\S+", re.I)


def clean_answer(text: str, max_chars: int) -> str:
    """A visit's answer with nothing that points outside the suite: images become their text,
    links to other sites (any scheme, ``//host``) their text, raw HTML goes, a bare address is
    replaced; the suite's own links (``/dash/...``, ``#...``) stay. Cut at ``max_chars``."""

    text = _IMAGE.sub(lambda found: found.group(1), text)
    text = _EXTERNAL_LINK.sub(lambda found: found.group(1), text)
    text = _HTML.sub("", text)
    text = _ADDRESS.sub(t("(address removed)"), text)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …"
    return text


def is_visit(owner: str | None) -> bool:
    """A chat's owner is a demo visit (``<visitor>#visit:<id>``), not a person."""

    return bool(owner) and VISIT_OWNER in str(owner)


def plant_day_start() -> str:
    """The start of the plant's day, as stored times are written (UTC text)."""

    return utc_text(
        datetime.now(plant_timezone()).replace(hour=0, minute=0, second=0, microsecond=0)
    )


# Seconds visits stop asking after the model service refused the installation (429, 401, 403).
PAUSE_SECONDS = 600
# The service codes that pause the visits: no credit or limited (429), key refused (401, 403).
PAUSING_CODES = (401, 403, 429)


def unavailable() -> str:
    """What a visit reads when the assistant cannot answer: never the service's own error."""

    return t(
        "The assistant cannot answer right now. Try again later; the rest of the demo works as "
        "usual."
    )


# The model's tokens one answer spent (``specialists.model.ChatModel.usage``).
USAGE_KEYS = ("calls", "input", "cached", "output", "reasoning")


class DemoQuestions(Store):
    """Every question a public demo's visits asked the model: who (the visit), from where (the
    client's address, its /64 for IPv6), when, and what its answer spent. The limits count here,
    not in the chats, so they hold whatever happens to a visit's chats; it stays in the
    installation's own database when visits get databases of their own (``DEMO_SHARED``)."""

    DEMO_SHARED = True
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS assistant_demo_questions (
        question_id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner TEXT NOT NULL,
        address TEXT NOT NULL DEFAULT '',
        asked_at TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'asked',
        usage_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE INDEX IF NOT EXISTS idx_assistant_demo_questions_owner
        ON assistant_demo_questions(owner, question_id);
    CREATE INDEX IF NOT EXISTS idx_assistant_demo_questions_at
        ON assistant_demo_questions(asked_at);
    CREATE INDEX IF NOT EXISTS idx_assistant_demo_questions_address
        ON assistant_demo_questions(address, asked_at);
    """

    def record(self, owner: str, address: str) -> int:
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "INSERT INTO assistant_demo_questions (owner, address, asked_at) VALUES (?, ?, ?)",
                (owner, address[:80], self._now()),
            )
        return int(cursor.lastrowid or 0)

    def count(
        self, *, owner: str = "", address: str = "", since: str = "", answered: bool = False
    ) -> int:
        """Questions of one visit, or from one address, or all of them, since ``since``;
        ``answered`` leaves out those the assistant could not answer (a visit keeps them)."""

        where, values = ["asked_at >= ?"], [since]
        if answered:
            where.append("state != 'failed'")
        if owner:
            where.append("owner = ?")
            values.append(owner)
        if address:
            where.append("address = ?")
            values.append(address)
        with self._lock, self._connect() as connection:
            (found,) = connection.execute(
                f"SELECT COUNT(*) FROM assistant_demo_questions WHERE {' AND '.join(where)}",
                values,
            ).fetchone()
        return int(found)

    def answered(self, owner: str, state: str, usage: dict[str, int]) -> None:
        """The visit's latest question was answered (``done``) or not (``failed``); its tokens
        are added (an answer asked again after a failure spends more)."""

        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT question_id, usage_json FROM assistant_demo_questions WHERE owner = ? "
                "ORDER BY question_id DESC LIMIT 1",
                (owner,),
            ).fetchone()
            if row is None:
                return
            try:
                total = json.loads(row[1] or "{}")
            except ValueError:
                total = {}
            for key in USAGE_KEYS:
                value = usage.get(key) if isinstance(usage, dict) else None
                if isinstance(value, int) and value > 0:
                    total[key] = int(total.get(key, 0)) + value
            connection.execute(
                "UPDATE assistant_demo_questions SET state = ?, usage_json = ? WHERE question_id = ?",
                (state, json.dumps(total), row[0]),
            )

    def totals(self, since: str) -> dict[str, int]:
        """The visits' questions since ``since``: how many, answered, failed, and the tokens."""

        found = {key: 0 for key in ("questions", "answered", "failed", *USAGE_KEYS)}
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT state, usage_json FROM assistant_demo_questions WHERE asked_at >= ?",
                (since,),
            ).fetchall()
        for state, usage_json in rows:
            found["questions"] += 1
            if state == "done":
                found["answered"] += 1
            elif state == "failed":
                found["failed"] += 1
            try:
                usage = json.loads(usage_json or "{}")
            except ValueError:
                usage = {}
            for key in USAGE_KEYS:
                value = usage.get(key) if isinstance(usage, dict) else None
                if isinstance(value, int):
                    found[key] += value
        return found


class DemoLimits:
    """Whether a visit's question may go to the model now. The visit's, the address's and the
    day's counts are read from ``DemoQuestions``; only the minute's window is in memory."""

    def __init__(self) -> None:
        self._minute: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._paused_until = 0.0

    def pause(self, seconds: float = PAUSE_SECONDS, now: float | None = None) -> None:
        """The model service refused the installation (no credit, key refused, limited): visits
        stop asking for a while instead of each one failing."""

        now = time.monotonic() if now is None else now
        self._paused_until = max(self._paused_until, now + seconds)

    def paused(self, now: float | None = None) -> bool:
        return (time.monotonic() if now is None else now) < self._paused_until

    def left(self, settings: DemoAssistant, questions: DemoQuestions, owner: str) -> int:
        return max(0, settings.questions - questions.count(owner=owner, answered=True))

    def take(
        self,
        settings: DemoAssistant,
        questions: DemoQuestions,
        owner: str,
        address: str,
        now: float | None = None,
    ) -> str | None:
        """None when the question may go to the model (it is then counted), else why not, for
        the visitor."""

        with self._lock:
            if self.paused(now):
                return unavailable()
            if questions.count(owner=owner, answered=True) >= settings.questions:
                return t(
                    "This visit used its {count} questions to the assistant. Thank you for "
                    "trying it! Install PlantCraft to use it without limits, with your own model.",
                    count=settings.questions,
                )
            today = plant_day_start()
            if questions.count(since=today) >= settings.daily:
                return t(
                    "The assistant answered all the questions it takes today in this demo. Try "
                    "again tomorrow."
                )
            if questions.count(address=address, since=today) >= settings.per_address:
                return t(
                    "You asked the assistant {count} questions today from this address, the most "
                    "it takes. Try again tomorrow.",
                    count=settings.per_address,
                )
            now = time.monotonic() if now is None else now
            events = self._minute[address]
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= settings.per_minute:
                return t("Too many questions in a minute. Wait a little and ask again.")
            events.append(now)
            if len(self._minute) > 50_000:  # forget idle addresses
                for key in [key for key, value in self._minute.items() if not value]:
                    del self._minute[key]
            questions.record(owner, address)
        return None
