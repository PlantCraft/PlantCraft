"""How a to-do repeats: the choices, and the days it is due."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from plantcraft.i18n import t

# English constants; read them through ``t()``.
TODO_REPEATS = {
    "": "Does not repeat",
    "daily": "Every day",
    "weekdays": "Monday to Friday",
    "days": "On some days of the week",
}


def todo_repeats() -> list[dict[str, str]]:
    return [{"id": key, "label": t(label)} for key, label in TODO_REPEATS.items()]


def todo_due(todo: dict[str, Any], day: date) -> bool:
    """Whether a repeated to-do falls on ``day`` (any day, for one that does not repeat)."""

    repeat = todo.get("repeat") or ""
    if repeat == "daily":
        return True
    if repeat == "weekdays":
        return day.weekday() < 5
    if repeat == "days":
        return day.weekday() in set(todo.get("days") or [])
    return True


def next_due(todo: dict[str, Any], after: date) -> date | None:
    """The first day after ``after`` a repeated to-do falls on (None when it does not repeat)."""

    if not todo.get("repeat"):
        return None
    day = after + timedelta(days=1)
    for _ in range(8):
        if todo_due(todo, day):
            return day
        day += timedelta(days=1)
    return None
