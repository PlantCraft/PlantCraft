"""What each section of a report shows over its period, read from PlantCraft API v1.

Cards read through ``query.cards.read_card`` with the report's period as their window, so a
report draws exactly what the same card shows on a dashboard. Events are the latest of each kind
API v1 keeps, cut to the period. A section that cannot be read says why (``error``) and the rest
of the report is still made; only a refused token stops it, so the caller can say so.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.client import PlantCraftError, Unauthorized

from dashcraft.dashboards.model import window_seconds
from dashcraft.i18n import t
from dashcraft.query.cards import Reader, read_card
from dashcraft.reports import alarm_performance
from dashcraft.reports import assistant as helper
from dashcraft.reports.model import EventsSpec, Section

# Writes an assistant section: (section_id, spec, facts, start, end) -> Markdown
# (``ReportService.writer``).
Writer = Callable[[str, helper.AssistantSpec, dict[str, Any], datetime, datetime], str]

# Events of one kind read per section: the period's, newest first, up to this many.
EVENTS_READ = 500


def _instant(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _subject_name(reader: Reader, subject: str, names: dict[str, str]) -> str:
    if subject in names:
        return names[subject]
    kind, _, item = subject.partition(":")
    name = item or subject
    if kind == "asset" and item:
        try:
            name = str(reader.asset(item).get("name") or item)
        except Unauthorized:
            raise
        except PlantCraftError:
            name = item
    elif kind == "app":
        name = item
    names[subject] = name
    return name


# The worse of two severities an event may carry.
SEVERITY_RANK = {"ok": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}


def humanize(value: str) -> str:
    """``stiction_screening`` -> "Stiction screening": an id people can read."""

    words = str(value).replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else words


def group_head(group_by: str) -> str:
    """The heading of the column the groups are named in."""

    if group_by == "subject":
        return t("About")
    if group_by == "kind":
        return t("Event")
    if group_by == "severity":
        return t("Severity")
    key = group_by.removeprefix("payload.")
    return humanize(key.removesuffix("_id") if key.endswith("_id") else key)


def _group_of(row: dict[str, Any], group_by: str, listed: dict[str, Any]) -> tuple[str, str]:
    """(key, label) of the group ``row`` falls in."""

    if group_by == "subject":
        return listed["subject"] or "", listed["subject_name"] or t("Not given")
    if group_by == "kind":
        return listed["kind"] or "", listed["title"] or t("Not given")
    if group_by == "severity":
        return listed["severity"], humanize(listed["severity"])
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    key = group_by.removeprefix("payload.")
    value = payload.get(key)
    if value is None or value == "":
        return "", t("Not given")
    # ``method_id`` is named by ``method_name`` where the app gives it.
    name = payload.get(f"{key.removesuffix('_id')}_name") if key.endswith("_id") else None
    return str(value), str(name or humanize(str(value)))


def group_events(
    rows: list[dict[str, Any]], listed: list[dict[str, Any]], group_by: str
) -> list[dict[str, Any]]:
    """The events counted by ``group_by``, the most first (ties: the latest first), each with
    its count, its share of all, its latest time and what happened then, and the worst
    severity among them."""

    groups: dict[str, dict[str, Any]] = {}
    total = len(rows)
    for row, item in zip(rows, listed, strict=True):
        key, label = _group_of(row, group_by, item)
        group = groups.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "count": 0,
                "first": None,
                "last": None,
                "summary": "",
                "severity": "ok",
            },
        )
        group["count"] += 1
        at = str(item.get("at") or "")
        if group["last"] is None or at > group["last"]:
            group["last"], group["summary"] = at, item.get("summary") or ""
        if group["first"] is None or at < group["first"]:
            group["first"] = at
        if SEVERITY_RANK.get(item["severity"], 1) > SEVERITY_RANK.get(group["severity"], 1):
            group["severity"] = item["severity"]
    ranked = sorted(groups.values(), key=lambda g: g["last"] or "", reverse=True)
    ranked.sort(key=lambda g: g["count"], reverse=True)
    for group in ranked:
        group["share"] = round(100 * group["count"] / total, 1) if total else 0.0
    return ranked


def read_events(reader: Reader, spec: EventsSpec, start: datetime, end: datetime) -> dict:
    """The events of ``spec.kinds`` between ``start`` and ``end``: how many of each, and the
    newest ``spec.limit`` of them all, or (``spec.group_by``) the ``spec.limit`` largest groups
    of them."""

    try:
        titles = reader.event_titles()
    except Unauthorized:
        raise
    except PlantCraftError:
        titles = {}
    found: list[dict[str, Any]] = []
    counts = []
    for kind in spec.kinds:
        rows = reader.events(kind, EVENTS_READ)
        inside = [
            row
            for row in rows
            if (at := _instant(row.get("at"))) is not None and start <= at <= end
        ]
        oldest = _instant(rows[0].get("at")) if rows else None
        more = len(rows) >= EVENTS_READ and oldest is not None and oldest >= start
        counts.append(
            {"kind": kind, "title": titles.get(kind, kind), "count": len(inside), "more": more}
        )
        found.extend(inside)
    found.sort(key=lambda row: str(row.get("at") or ""), reverse=True)
    names: dict[str, str] = {}
    shown = found if spec.group_by else found[: spec.limit]
    listed = [
        {
            "at": row.get("at"),
            "kind": row.get("kind"),
            "title": titles.get(str(row.get("kind")), str(row.get("kind") or "")),
            "subject": row.get("subject"),
            "subject_name": _subject_name(reader, str(row.get("subject") or ""), names),
            "summary": row.get("summary") or "",
            "severity": str(row.get("severity") or "info"),
        }
        for row in shown
    ]
    out: dict[str, Any] = {
        "kind": "events",
        "counts": counts,
        "total": len(found),
        "events": listed[: spec.limit],
        "range": {"start": start.isoformat(), "end": end.isoformat()},
    }
    if spec.group_by:
        groups = group_events(found, listed, spec.group_by)
        out.update(
            group_by=spec.group_by,
            group_head=group_head(spec.group_by),
            groups=groups[: spec.limit],
            group_total=len(groups),
        )
    return out


def section_problems(data: dict[str, Any] | None) -> bool:
    """Whether a section could not be read in full (a signal of a card, say)."""

    if not data:
        return True
    rows = [*(data.get("rows") or []), *(data.get("lines") or [])]
    return any(row.get("error") for row in rows)


def read_section(reader: Reader, section: Section, period: str) -> dict[str, Any]:
    """``{"section", "data", "error"}`` for one section over ``period`` ending now."""

    out: dict[str, Any] = {"section": section.model_dump(), "data": None, "error": None}
    if section.kind in ("text", "break"):
        return out
    end = reader.clock()
    start = end - timedelta(seconds=window_seconds(period))
    try:
        if section.kind == "card" and section.card is not None:
            out["data"] = read_card(reader, section.card, None, period)
        elif section.kind == "events" and section.events is not None:
            out["data"] = read_events(reader, section.events, start, end)
        elif section.kind == "alarms" and section.alarms is not None:
            out["data"] = alarm_performance.read(reader, section.alarms.asset_id, period)
            out["error"] = out["data"]["problem"] or None
        elif section.kind == "assistant" and section.assistant is not None:
            facts = helper.gather(reader, section.assistant, start, end)
            out["data"] = {
                "kind": "assistant",
                "assets": len(facts["assets"]),
                "results": len(facts["results"]),
                "events": facts["events_total"],
                "event_counts": facts["event_counts"],
            }
    except Unauthorized:
        raise
    except PlantCraftError as exc:
        out["error"] = t("PlantCraft could not answer: {detail}", detail=exc.detail)
    return out


def write_assistant(
    reader: Reader, section: Section, period: str, writer: Writer
) -> dict[str, Any]:
    """An assistant section written now: read as a text cell (so every file format draws it as
    one), with what the model was given in ``assistant``. A model that cannot write leaves the
    reason in the cell and ``error``, and the rest of the report is still made."""

    assert section.assistant is not None
    end = reader.clock()
    start = end - timedelta(seconds=window_seconds(period))
    facts = helper.gather(reader, section.assistant, start, end)
    error = None
    try:
        body = helper.clean_text(writer(section.section_id, section.assistant, facts, start, end))
        if not body:
            raise ValueError(t("The model answered nothing."))
    except Unauthorized:
        raise
    except Exception as exc:  # noqa: BLE001 - no model, a refusal, a timeout: said in the cell
        error = str(getattr(exc, "detail", None) or exc)[:300]
        body = t("The assistant could not write this section: {reason}", reason=error)
    text = helper.section_text(section.title, body, facts)
    cell = {**section.model_dump(), "kind": "text", "title": "", "text": text}
    return {
        "section": cell,
        "data": None,
        "error": error,
        "assistant": {
            "section_id": section.section_id,
            "version": section.assistant.version,
            "text": body if error is None else "",
            "facts": {
                "assets": len(facts["assets"]),
                "results": len(facts["results"]),
                "events": facts["events_total"],
            },
        },
    }


def read_sections(
    reader: Reader,
    sections: list[dict[str, Any]],
    period: str,
    writer: Writer | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Every section of a report, and how many could not be read in full. With ``writer``,
    assistant sections are written by the model; without, they are left out (a page shows
    the last written text instead)."""

    items = []
    problems = 0
    for raw in sections:
        try:
            section = Section.model_validate(raw)
        except ValueError:
            items.append(
                {
                    "section": {"kind": "text", "title": "", "text": ""},
                    "data": None,
                    "error": t("This section no longer fits the report's rules."),
                }
            )
            problems += 1
            continue
        if section.kind == "assistant":
            if writer is None:
                continue
            item = write_assistant(reader, section, period, writer)
            problems += 1 if item["error"] else 0
            items.append(item)
            continue
        item = read_section(reader, section, period)
        if section.kind in ("card", "events", "alarms") and (
            item["error"] or section_problems(item["data"])
        ):
            problems += 1
        items.append(item)
    return items, problems
