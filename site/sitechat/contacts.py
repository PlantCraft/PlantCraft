"""Contact requests and the questions visitors ask, kept in the site's data folder.

Contacts go to `contacts.jsonl` (readable by the site's user only) and, when
SITE_CONTACT_WEBHOOK is set, to that address as one JSON message, so the team hears at once.
Questions go to `questions.jsonl` without any address or name: they say what visitors want to
know and where the documentation falls short.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

EMAIL = re.compile(r"^[^@\s<>\"']{1,64}@[^@\s<>\"']{1,190}\.[a-z]{2,24}$", re.I)


class Contact(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    company: str = Field(default="", max_length=160)
    need: str = Field(min_length=1, max_length=2000)
    # The visitor's questions in the chat, when they agreed to send them along.
    conversation: list[str] = Field(default_factory=list, max_length=12)
    # Left empty by people; bots that fill every field are dropped without a word.
    website: str = Field(default="", max_length=200)

    @field_validator("name", "company", "need")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip()
        if not EMAIL.match(value):
            raise ValueError("not an email address")
        return value

    @field_validator("conversation")
    @classmethod
    def _conversation(cls, value: list[str]) -> list[str]:
        return [v[:1200] for v in value]


class Inbox:
    def __init__(self, folder: Path, webhook: str = "", log_questions: bool = True):
        self.folder = folder
        self.webhook = webhook
        self.log_questions = log_questions
        self._lock = threading.Lock()

    def _append(self, name: str, record: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / name
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(line)

    def add_contact(self, contact: Contact) -> None:
        record = {"time": _now(), **contact.model_dump(exclude={"website"})}
        self._append("contacts.jsonl", record)
        if self.webhook:
            _notify(self.webhook, record)

    def add_question(self, question: str, answered: bool, contact: bool, sources: list[str]):
        if not self.log_questions:
            return
        self._append(
            "questions.jsonl",
            {
                "time": _now(),
                "question": question[:1200],
                "answered": answered,
                "contact": contact,
                "sources": sources,
            },
        )

    def contacts(self) -> list[dict]:
        return self._read("contacts.jsonl")

    def questions(self) -> list[dict]:
        return self._read("questions.jsonl")

    def _read(self, name: str) -> list[dict]:
        path = self.folder / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _notify(url: str, record: dict) -> None:
    """One message to a chat webhook (Slack, Discord, Teams, ntfy...); a failure is not the visitor's."""
    text = (
        f"New contact from the site: {record['name']} <{record['email']}>"
        f"{' (' + record['company'] + ')' if record['company'] else ''}\n{record['need']}"
    )
    body = json.dumps({"text": text, "content": text[:1900], "contact": record}).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except Exception:  # noqa: BLE001 - the record is on disk; the notice is best effort
        pass
