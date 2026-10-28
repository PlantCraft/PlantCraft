"""omc's messages (``getErrorString()``) as a list a person can act on.

omc writes one message per entry, optionally prefixed by where it is::

    [/jobs/work/<id>/files/Tank.mo:7:1-7:8:writable] Error: Expected token of type SEMICOLON
    Warning: Requested package Modelica of version 3.2.3, but this package was already loaded
    Notification: Automatically loaded package Complex 4.0.0 due to uses annotation

A message can span several lines; it ends where the next one starts. Paths in a job's files
become the project's own paths (``Tank.mo``); library paths become the library's (``Modelica/
Blocks/package.mo``, read only), and anything else is dropped: the runner's folders are never
shown.
"""

from __future__ import annotations

import re
from typing import Any

HEAD = re.compile(
    r"^(?:\[(?P<file>[^\]\n]*?):(?P<line>\d+):(?P<column>\d+)-(?P<end_line>\d+):(?P<end_column>\d+)"
    r":(?P<mode>readonly|writable)\]\s*)?(?P<level>Error|Warning|Notification):\s?(?P<text>.*)$"
)
JOB_FILE = re.compile(r"^/(?:[^/\n]+/)*?files/(?P<path>.+)$")
LIBRARY_FILE = re.compile(r"^/opt/modelica/(?P<path>.+)$")
LEVELS = {"Error": "error", "Warning": "warning", "Notification": "info"}
MAX_MESSAGES = 200
MAX_TEXT = 2000


def _where(path: str) -> tuple[str | None, bool]:
    """(the path a person sees, whether it is the project's own file)."""

    library = LIBRARY_FILE.match(path)
    if library:
        return library.group("path"), False
    own = JOB_FILE.match(path)
    if own:
        return own.group("path"), True
    return None, False


def parse(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        head = HEAD.match(line)
        if head:
            if current is not None:
                messages.append(current)
            file, own = _where(head.group("file") or "")
            current = {
                "level": LEVELS[head.group("level")],
                "text": head.group("text").strip(),
                "file": file,
                "own": own,
                "line": int(head.group("line")) if file and head.group("line") else None,
                "column": int(head.group("column")) if file and head.group("column") else None,
                "end_line": int(head.group("end_line"))
                if file and head.group("end_line")
                else None,
                "end_column": int(head.group("end_column"))
                if file and head.group("end_column")
                else None,
            }
        elif current is not None and line.strip():
            current["text"] = f"{current['text']}\n{line.strip()}"
    if current is not None:
        messages.append(current)
    for message in messages:
        message["text"] = scrub(message["text"])[:MAX_TEXT]
    return messages[:MAX_MESSAGES]


def scrub(text: str) -> str:
    """The runner's folders out of a text: job paths become project paths."""

    text = text.replace("/opt/modelica/", "")
    return re.sub(r"(?<![\w.])/[^\s\"']*?/(?:files|out)/", "", text)


def simulation_log(text: str) -> list[dict[str, Any]]:
    """The simulation's own log (``LOG_ASSERT | warning | ...``) as messages, without the
    debug lines."""

    messages = []
    for raw in (text or "").splitlines():
        parts = [part.strip() for part in raw.split("|", 2)]
        if len(parts) == 3 and parts[0].startswith("LOG_"):
            level = {"error": "error", "warning": "warning", "assert": "error"}.get(
                parts[1], "info"
            )
            if parts[1] == "debug":
                if messages:
                    messages[-1]["text"] = f"{messages[-1]['text']}\n{parts[2]}"
                continue
            text = scrub(parts[2].lstrip("| ").strip())
            messages.append({"level": level, "text": text[:MAX_TEXT], "file": None})
        elif raw.strip(" |") and messages:
            line = scrub(raw.strip().lstrip("| ").strip())
            messages[-1]["text"] = f"{messages[-1]['text']}\n{line}"[:MAX_TEXT]
        elif raw.strip():
            messages.append({"level": "info", "text": scrub(raw.strip())[:MAX_TEXT], "file": None})
    return messages[:MAX_MESSAGES]
