"""An events section that counts its events instead of listing them (``EventsSpec.group_by``):
the groups as one ranked table, and the sentence that names the largest, the same in every
format (PDF, Word, HTML, Markdown and the page)."""

from __future__ import annotations

from typing import Any, Protocol

from dashcraft.i18n import t

# An event's severity -> the state a row is coloured in.
ROW_STATE = {"critical": "alarm", "error": "alarm", "warning": "warning"}


class _Clock(Protocol):
    def text(self, value: Any, form: str = ...) -> str: ...


def lead(data: dict[str, Any]) -> str:
    """ "Most often: FIC-1003, 9 of 24 (37.5%)." or nothing without groups."""

    groups = data.get("groups") or []
    total = int(data.get("total") or 0)
    if not groups or not total:
        return ""
    top = groups[0]
    words = t(
        "Most often: {label}, {count} of {total} ({share}%).",
        label=top["label"],
        count=top["count"],
        total=total,
        share=_share(top.get("share")),
    )
    count = int(data.get("group_total") or len(groups))
    return f"{words} " + t("{n} in all.", n=count) if count > 1 else words


def _share(value: Any) -> str:
    number = float(value or 0)
    return f"{number:.0f}" if number.is_integer() else f"{number:.1f}"


def table(data: dict[str, Any], clock: _Clock) -> tuple[list[str], list[list[str]], list[str]]:
    """(head, rows, row states) of the ranked groups: rank, the group, how many, their share,
    the latest and what happened then."""

    head = [
        "#",
        str(data.get("group_head") or t("Group")),
        t("Count"),
        t("Share"),
        t("Latest"),
        t("Latest event"),
    ]
    rows = [
        [
            str(index),
            str(group.get("label") or ""),
            str(group.get("count") or 0),
            f"{_share(group.get('share'))}%",
            clock.text(group.get("last"), "%d %b %H:%M"),
            str(group.get("summary") or ""),
        ]
        for index, group in enumerate(data.get("groups") or [], start=1)
    ]
    states = [
        ROW_STATE.get(str(group.get("severity") or ""), "") for group in data.get("groups") or []
    ]
    return head, rows, states


def more(data: dict[str, Any]) -> str:
    """Says the table stops before the last group."""

    shown, count = len(data.get("groups") or []), int(data.get("group_total") or 0)
    if count > shown:
        return t("The {n} largest of {total} groups are listed.", n=shown, total=count)
    return ""


__all__ = ["lead", "more", "table"]
