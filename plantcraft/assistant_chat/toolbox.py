"""The tools the assistant's model is given (the read-only MCP server's, ``show_chart`` and
``read_help``), how big a tool answer may be, and how much the assistant may read per person
and day (``ReadBudget``)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from plantcraft.assistant_access import mcp
from plantcraft.assistant_chat.engine_common import CHART, CHART_SIGNALS, HELP, TOOL_TEXT
from plantcraft.assistant_works import CREATE, PROPOSE, Work
from plantcraft.config import plant_timezone
from plantcraft.db import utc_text


def chart_tool() -> dict[str, Any]:
    return {
        "name": CHART,
        "description": (
            "Draw a time chart of up to 6 signals for the person, from the plant's history. "
            "Use it whenever the person asks for a chart, a trend or a series, or when a trend "
            "explains your answer. The chart appears in the chat; you get back each signal's "
            "points, first, last, min, max and mean to comment on. Find the signal ids first "
            "(search_signals, search_assets or get_asset). Times are ISO 8601 in UTC with Z (or "
            "with an offset); default: the last 24 h. History ends now: a window ahead of now is "
            "moved back to end now. A signal with 0 points has no data in that period: say so, and look for the "
            "period that has data (signal_value gives the last sample's time)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "signal_ids": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 300},
                    "minItems": 1,
                    "maxItems": CHART_SIGNALS,
                },
                "start": {"type": "string", "maxLength": 64},
                "end": {"type": "string", "maxLength": 64},
                "title": {"type": "string", "maxLength": 120},
            },
            "required": ["signal_ids"],
            "additionalProperties": False,
        },
    }


def help_tool() -> dict[str, Any]:
    return {
        "name": HELP,
        "description": (
            "Read the suite's Help: the guides that say what PlantCraft and Desk are, how a page "
            "or a feature works and what a concept means. Without arguments: the list of guides. "
            "With query: the guides that mention those words, with the lines around them. With "
            "document_id: that guide (long ones are cut). Use it to explain the platform, never "
            "to answer about the plant's data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "maxLength": 80},
                "query": {"type": "string", "maxLength": 120},
            },
            "additionalProperties": False,
        },
    }


# The suite's Help as the model reads it: the guides' index and one guide's Markdown (the HTTP
# layer gives them: ``api/help.py``).
HelpIndex = Callable[[], list[dict[str, str]]]
HelpRead = Callable[[str], str]


def read_help(index: HelpIndex, read: HelpRead, arguments: dict[str, Any]) -> Any:
    """``read_help``'s answer: the index, the guides that mention words, or one guide."""

    guides = index()
    known = {item["document_id"] for item in guides}
    wanted = str(arguments.get("document_id") or "").strip()
    if wanted:
        if wanted not in known:
            raise ValueError(f"No guide {wanted}; call read_help without arguments for the list")
        text = read(wanted)
        if len(text) > TOOL_TEXT:
            text = text[:TOOL_TEXT] + "\n[cut; ask with query for a part]"
        return {"document_id": wanted, "markdown": text}
    words = [word for word in str(arguments.get("query") or "").lower().split() if len(word) > 2]
    if not words:
        return {"guides": guides}
    found = []
    for item in guides:
        lines = read(item["document_id"]).splitlines()
        hits = [n for n, line in enumerate(lines) if any(word in line.lower() for word in words)]
        if hits:
            parts = ["\n".join(lines[max(0, n - 1) : n + 3]) for n in hits[:4]]
            found.append({**item, "hits": len(hits), "excerpts": parts})
    found.sort(key=lambda item: -item["hits"])
    return {"query": " ".join(words), "guides": found[:4]}


def _line(item: Any) -> str:
    if isinstance(item, dict):
        return ": ".join(str(value) for value in item.values() if value not in (None, ""))
    return str(item).strip()


def as_lists(work: Work, given: Any) -> Any:
    """``given`` with each list field as a list of lines: a model may write one as text (one
    item per line, or split by ";") or as an object of name to description."""

    if not isinstance(given, dict):
        return given
    fixed = dict(given)
    for field in work.spec.fields:
        value = fixed.get(field.key)
        if (
            field.type != "list"
            or value is None
            or isinstance(value, list)
            and all(isinstance(item, str) for item in value)
        ):
            continue
        if isinstance(value, str):
            parts = value.splitlines() if "\n" in value else value.split(";")
            items = [part.strip().lstrip("-*• ").strip() for part in parts]
        elif isinstance(value, dict):
            items = [
                f"{key}: {_line(item)}" if _line(item) else str(key) for key, item in value.items()
            ]
        elif isinstance(value, list):
            items = [_line(item) for item in value]
        else:
            continue
        fixed[field.key] = [item for item in items if item]
    return fixed


def tool_title(name: str) -> str:
    """A tool's title for the person (English; the page translates it)."""

    if name == CHART:
        return "Draw a chart"
    if name == HELP:
        return "Read the Help"
    if name in (PROPOSE, CREATE):
        return "Prepare the card"
    found = mcp.BY_NAME.get(name)
    return found.title if found else name


def tools(with_help: bool = False) -> list[dict[str, Any]]:
    """What the model may call: the MCP server's read-only tools, the chart and the Help."""

    listed = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.describe()["inputSchema"],
        }
        for tool in mcp.TOOLS
    ]
    return [*listed, chart_tool(), *([help_tool()] if with_help else [])]


def refs_of(arguments: dict[str, Any]) -> list[str]:
    """The plant objects a tool call names, as references (``asset:FIC-101``, ``signal:...``)."""

    found: list[str] = []
    for key in ("asset_id", "under"):
        if arguments.get(key):
            found.append(f"asset:{arguments[key]}")
    if arguments.get("signal_id"):
        found.append(f"signal:{arguments['signal_id']}")
    found += [f"signal:{item}" for item in arguments.get("signal_ids") or []]
    for key in ("ref", "subject"):
        value = str(arguments.get(key) or "")
        if ":" in value:
            found.append(value)
    if arguments.get("object_id") and arguments.get("app") and arguments.get("kind"):
        found.append(f"{arguments['kind']}:{arguments['app']}/{arguments['object_id']}")
    return found


def fit(payload: Any) -> Any:
    """A tool's answer within ``TOOL_TEXT``: a list keeps whole items and says its total (a list
    cut in the middle of its text was counted as 28 of 50 valves, 2026-10-26)."""

    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= TOOL_TEXT:
        return payload
    listed = payload if isinstance(payload, list) else None
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        listed = payload["items"]
    if listed:
        total = payload.get("total", len(listed)) if isinstance(payload, dict) else len(listed)
        kept: list[Any] = []
        size = 200
        for item in listed:
            size += len(json.dumps(item, ensure_ascii=False, default=str)) + 2
            if size > TOOL_TEXT:
                break
            kept.append(item)
        return {
            "total": total,
            "items": kept,
            "note": f"{len(kept)} of {total} shown (the answer was too long): count from total, "
            "and narrow the query to read the rest",
        }
    return text[:TOOL_TEXT] + f"\n[cut: {len(text) - TOOL_TEXT} more characters; narrow the query]"


def summary(arguments: dict[str, Any]) -> str:
    """A tool call's arguments as one short line for the person."""

    parts = []
    for key, value in arguments.items():
        text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        parts.append(f"{key}: {text}")
    line = "; ".join(parts)
    return line if len(line) <= 160 else f"{line[:157]}…"


def reads_of(name: str, arguments: dict[str, Any]) -> int:
    """What one tool call reads, counted for the daily limit: a signal each, at least one."""

    if name == HELP:
        return 0
    ids = arguments.get("signal_ids")
    if isinstance(ids, list):
        return max(1, len(ids))
    return 1


class ReadBudget:
    """How much the assistant read for each person today (security backlog B13, 2026-10-31).

    Each tool call counts the signals it reads (``reads_of``). Past ``daily`` the assistant
    reads nothing more for that person until the plant's next day, and the audit log gets one
    ``assistant.read_limit`` that day. The count starts from today's ``assistant.tool`` records
    of the audit log, so a restart does not reset it; each server process keeps its own."""

    def __init__(self, audit: Any, daily: int):
        self.audit = audit
        self.daily = daily
        self._used: dict[tuple[str, str], int] = {}
        self._warned: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _today() -> datetime:
        return datetime.now(plant_timezone()).replace(hour=0, minute=0, second=0, microsecond=0)

    def _seed(self, username: str, since: datetime) -> int:
        try:
            rows = self.audit.list(
                username=username, action="assistant.tool", since=utc_text(since), limit=5_000
            )
        except Exception:  # an audit log that cannot be read starts the day at zero
            return 0
        used = 0
        for row in rows:
            detail = row.get("detail") if isinstance(row, dict) else None
            arguments = detail.get("arguments") if isinstance(detail, dict) else None
            name = str(row.get("subject") or "").removeprefix("tool:")
            used += reads_of(name, arguments if isinstance(arguments, dict) else {})
        return used

    def spend(self, username: str, amount: int, limit: int | None = None) -> bool:
        """Counts ``amount`` reads for ``username``; False (nothing counted) past the limit
        (``limit``: another than the daily one, a public demo visit's)."""

        if amount <= 0:
            return True
        daily = self.daily if limit is None else limit
        since = self._today()
        key = (username, since.date().isoformat())
        with self._lock:
            if key not in self._used:
                self._used = {k: v for k, v in self._used.items() if k[1] == key[1]}
                self._used[key] = self._seed(username, since)
            if self._used[key] + amount > daily:
                first = key not in self._warned
                self._warned.add(key)
                used = self._used[key]
            else:
                self._used[key] += amount
                return True
        if first:
            self.audit.record(
                username,
                "assistant.read_limit",
                f"user:{username}",
                {"read_today": used, "asked": amount, "daily_limit": daily},
                app_id="processcraft",
            )
        return False

    def used(self, username: str) -> int:
        key = (username, self._today().date().isoformat())
        with self._lock:
            return self._used.get(key, 0)
