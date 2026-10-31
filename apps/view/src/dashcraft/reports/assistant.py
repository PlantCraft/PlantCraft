"""An assistant section: a part of a report the language model writes, from what the apps found
about the assets a person picked (prototype, 2026-10-31, item E2 of the Saturday plan).

A person picks **assets** (checkboxes, or describes them and the model proposes the pick) and
the **analyses** to read (control loops, signal quality, alarms, data collection). When the
report is made, View reads, for those assets and the assets under them, the latest result each
app keeps and the events of the period, and hands the model only those facts plus the
person's **requirements** (the editable prompt). The model writes Markdown; the report keeps
it as a text cell, so the PDF, Word, HTML and Markdown files need nothing new.

Feedback closes the loop: a comment on a written section goes to the model with the
requirements and the text it wrote, and the model answers new requirements; each version is
kept (``store.ReportStore.assistant_versions``), so the next edition follows the comment and an
editor can always read why the prompt changed, or go back.

The model never acts: it reads the facts View sends and writes text. It is asked through
PlantCraft (``[[contributes.llm]]``: ``report-write`` and ``report-tune``), off until an
administrator gives it a model.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from dashcraft.i18n import t

WRITE_USE = "report-write"
TUNE_USE = "report-tune"
MAX_ASSETS = 60
MAX_REQUIREMENTS = 4000
# The facts sent in one call stay well under PlantCraft's 200 000 characters a call.
MAX_FACT_CHARS = 60_000
MAX_SUBJECTS = 300
EVENTS_READ = 500
EVENTS_SENT = 120

# What a person may ask the assistant to read: each analysis is the results and events the
# suite's apps already publish (their ``app.toml``), so this list grows with the apps.
ANALYSES: dict[str, dict[str, Any]] = {
    "loops": {
        "title": "Control loop performance",
        "results": ["linkcraft.loop_health"],
        "events": ["linkcraft.finding.opened", "linkcraft.finding.closed"],
    },
    "signals": {
        "title": "Signal quality",
        "results": ["linkcraft.signal_quality"],
        "events": ["histcraft.point.no_data", "linkcraft.protocol.alert"],
    },
    "alarms": {
        "title": "Alarms",
        "results": ["alarmcraft.alarm_state"],
        "events": ["alarmcraft.alarm.raised", "alarmcraft.flood.started"],
    },
    "collection": {
        "title": "Data collection",
        "results": [],
        "events": ["histcraft.collector.stalled", "histcraft.source.disconnected"],
    },
}

DEFAULT_REQUIREMENTS = """\
- Start with three to five lines a plant manager can read in a minute: what got worse, what
  got better, what needs a decision.
- Then one short paragraph per asset that needs attention, worst first, naming the asset and
  the evidence (status, score, the finding or alarm and when).
- End with a short list of suggested actions, each tied to an asset.
- Leave out assets with nothing to report; say how many were fine.
- Use only the facts given. When a fact is missing, say so; never guess a value."""


class AssistantSpec(BaseModel):
    """What an assistant section reads and how it writes (``Section.assistant``)."""

    asset_ids: list[str] = Field(min_length=1, max_length=MAX_ASSETS)
    # The assets under the picked ones too (a unit brings its loops).
    children: bool = True
    analyses: list[str] = Field(min_length=1, max_length=len(ANALYSES))
    requirements: str = Field(default=DEFAULT_REQUIREMENTS, max_length=MAX_REQUIREMENTS)
    # The version of the requirements now in use (``store.assistant_versions``); 1 at the start.
    version: int = Field(default=1, ge=1)

    @field_validator("asset_ids")
    @classmethod
    def _assets(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(v.strip() for v in values if v and v.strip()))
        if not cleaned:
            raise ValueError(t("Pick at least one asset."))
        return cleaned

    @field_validator("analyses")
    @classmethod
    def _analyses(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(values))
        unknown = [v for v in cleaned if v not in ANALYSES]
        if unknown:
            raise ValueError(t("Unknown analysis: {name}.", name=", ".join(unknown)))
        return cleaned

    @field_validator("requirements")
    @classmethod
    def _requirements(cls, value: str) -> str:
        return (value or "").strip() or DEFAULT_REQUIREMENTS


def analyses_catalog() -> list[dict[str, Any]]:
    """The analyses as the editor's checkboxes list them."""

    return [{"id": key, "title": t(item["title"])} for key, item in ANALYSES.items()]


# Reading the facts --------------------------------------------------------------------------


def _instant(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def scope(assets: list[dict[str, Any]], spec: AssistantSpec) -> list[dict[str, Any]]:
    """The picked assets and, with ``children``, every asset under them (breadth first)."""

    by_id = {str(item.get("id")): item for item in assets if item.get("id")}
    kids: dict[str, list[str]] = {}
    for item in assets:
        if item.get("parent_id"):
            kids.setdefault(str(item["parent_id"]), []).append(str(item["id"]))
    picked: list[str] = []
    queue = [a for a in spec.asset_ids if a in by_id]
    while queue and len(picked) < MAX_SUBJECTS:
        current = queue.pop(0)
        if current in picked:
            continue
        picked.append(current)
        if spec.children:
            queue.extend(kids.get(current, []))
    return [by_id[a] for a in picked]


def _compact_result(row: dict[str, Any]) -> dict[str, Any]:
    keep = ("status", "score", "summary", "updated_at", "stale", "expires_at")
    out = {k: row[k] for k in keep if row.get(k) not in (None, "")}
    details = row.get("details") if isinstance(row.get("details"), dict) else None
    if details:
        # A few numbers of the details, never a whole series.
        small = {
            k: v
            for k, v in list(details.items())[:8]
            if isinstance(v, (int, float, str, bool)) and len(str(v)) < 120
        }
        if small:
            out["details"] = small
    return out


def gather(reader: Any, spec: AssistantSpec, start: datetime, end: datetime) -> dict[str, Any]:
    """The facts the model gets: the assets in scope, the latest results of the analyses about
    them, and the period's events about them (newest first, capped). Read with the reader's
    token, so PlantCraft's permissions decide what reaches the model."""

    assets = scope(list(reader.assets(None) or []), spec)
    names = {f"asset:{a['id']}": str(a.get("name") or a["id"]) for a in assets}
    subjects = list(names)
    facts: dict[str, Any] = {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "analyses": [ANALYSES[a]["title"] for a in spec.analyses],
        "assets": [
            {
                "asset": names[f"asset:{a['id']}"],
                "kind": a.get("kind") or "",
                "description": str((a.get("attributes") or {}).get("description") or "")[:120],
            }
            for a in assets
        ],
        "results": [],
        "events": [],
        "event_counts": {},
    }
    for key in spec.analyses:
        for kind in ANALYSES[key]["results"]:
            try:
                rows = list(reader.client.results(subjects, kind=kind)) if subjects else []
            except Exception:  # noqa: BLE001 - an app not installed answers nothing
                rows = []
            for row in rows:
                subject = str(row.get("subject") or "")
                if subject in names:
                    facts["results"].append(
                        {"asset": names[subject], "analysis": kind, **_compact_result(row)}
                    )
        for kind in ANALYSES[key]["events"]:
            try:
                rows = reader.events(kind, EVENTS_READ)
            except Exception:  # noqa: BLE001 - an app not installed publishes nothing
                rows = []
            inside = [
                row
                for row in rows
                if str(row.get("subject") or "") in names
                and (at := _instant(row.get("at"))) is not None
                and start <= at <= end
            ]
            facts["event_counts"][kind] = len(inside)
            for row in inside:
                facts["events"].append(
                    {
                        "at": row.get("at"),
                        "kind": kind,
                        "asset": names[str(row["subject"])],
                        "severity": row.get("severity") or "info",
                        "summary": str(row.get("summary") or "")[:200],
                    }
                )
    facts["events"].sort(key=lambda e: str(e.get("at") or ""), reverse=True)
    all_events = list(facts["events"])
    facts["events_total"] = len(facts["events"])
    facts["events"] = facts["events"][:EVENTS_SENT]
    # Worst first, so a cut keeps what matters.
    rank = {"alarm": 0, "critical": 0, "error": 0, "warning": 1, "ok": 3}
    facts["results"].sort(key=lambda r: (rank.get(str(r.get("status")), 2), r.get("asset", "")))
    facts["by_asset"] = by_asset(facts, all_events)
    facts["legend"] = LEGEND
    text = json.dumps(facts, ensure_ascii=False, default=str)
    while len(text) > MAX_FACT_CHARS and (facts["events"] or facts["results"]):
        if facts["events"]:
            facts["events"] = facts["events"][: len(facts["events"]) // 2]
        else:
            facts["results"] = facts["results"][: len(facts["results"]) // 2]
        facts["cut"] = True
        text = json.dumps(facts, ensure_ascii=False, default=str)
    return facts


LEGEND = (
    "score: 0 to 100, LOWER IS WORSE. status: alarm is worse than warning, warning worse than ok. "
    "by_asset is already counted and ranked: rank 1 is the worst asset; use its counts, do not "
    "recount events."
)


def by_asset(facts: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per asset with a result or an event, counted here so a small model needs neither
    to count nor to sort: its worst status, lowest score, problems, and the period's alarms,
    findings opened and other events. Ranked worst first (rank 1)."""

    rows: dict[str, dict[str, Any]] = {}
    severity = {"alarm": 0, "critical": 0, "error": 0, "warning": 1, "ok": 3}

    def row(asset: str) -> dict[str, Any]:
        return rows.setdefault(
            asset,
            {
                "asset": asset,
                "status": "",
                "score": None,
                "problems": [],
                "alarms": 0,
                "critical_alarms": 0,
                "findings_opened": 0,
                "other_events": 0,
            },
        )

    for result in facts.get("results") or []:
        item = row(str(result.get("asset")))
        status = str(result.get("status") or "")
        if not item["status"] or severity.get(status, 2) < severity.get(item["status"], 2):
            item["status"] = status
        score = result.get("score")
        if isinstance(score, (int, float)) and (item["score"] is None or score < item["score"]):
            item["score"] = score
        if status not in ("ok", "") and result.get("summary"):
            item["problems"].append(str(result["summary"]))
    for event in events:
        item = row(str(event.get("asset")))
        kind = str(event.get("kind") or "")
        if kind.endswith(".alarm.raised"):
            item["alarms"] += 1
            item["critical_alarms"] += event.get("severity") == "critical"
        elif kind.endswith(".finding.opened"):
            item["findings_opened"] += 1
        else:
            item["other_events"] += 1
    ranked = sorted(
        rows.values(),
        key=lambda r: (
            severity.get(r["status"], 2),
            r["score"] if r["score"] is not None else 101,
            -r["alarms"],
            r["asset"],
        ),
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


# Asking the model ---------------------------------------------------------------------------

WRITE_SYSTEM = """\
You write one section of a plant report for process engineers. You get FACTS as JSON (the assets
in scope, the latest results the plant's analysis apps keep about them, the period's events) and
the REQUIREMENTS of the person who owns the report. Follow the requirements. Use only the facts:
name assets as the facts name them, quote numbers as given, and never invent a value, an asset or
an event. FACTS.legend says how to read scores; FACTS.by_asset is already counted and ranked
(rank 1 is the worst): take counts and order from it. Say nothing about earlier periods unless
the facts give them. Answer with the section's text in Markdown (headings start at ##), nothing
else."""

TUNE_SYSTEM = """\
You keep the requirements of a report section the language model writes. You get the CURRENT
REQUIREMENTS, the TEXT the model wrote with them, and a person's FEEDBACK on that text. Answer
the new requirements: the current ones changed so the next text follows the feedback. Keep what
the feedback does not touch, keep it a short list of rules, write it in the language of the
current requirements, and never add a rule that asks the writer to invent facts. The requirements
say how to write, never what the data is: no asset names or tags, no numbers or counts of this
period, no statement about which data exists. Keep the words of the feedback ("worst" means the
lowest score). Answer with the requirements only, no preface."""

SCOPE_SYSTEM = """\
You pick the assets a report should cover. You get ASSETS (id, name, kind, parent) as JSON and a
person's DESCRIPTION. Answer JSON only: {"asset_ids": [...], "analyses": [...], "why": "..."},
with ids from ASSETS only and analyses from ANALYSES only."""


def write_question(spec: AssistantSpec, facts: dict[str, Any], period_words: str) -> str:
    return (
        f"PERIOD: {period_words}\n\nREQUIREMENTS:\n{spec.requirements}\n\n"
        f"FACTS:\n{json.dumps(facts, ensure_ascii=False, default=str)}"
    )


def tune_question(requirements: str, text: str, feedback: str) -> str:
    return (
        f"CURRENT REQUIREMENTS:\n{requirements}\n\nTEXT:\n{text[:12000]}\n\nFEEDBACK:\n{feedback}"
    )


def scope_question(assets: list[dict[str, Any]], description: str) -> str:
    listed = [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "kind": a.get("kind"),
            "parent": a.get("parent_id"),
        }
        for a in assets[:2000]
    ]
    return (
        f"ANALYSES: {json.dumps(list(ANALYSES))}\n\nASSETS:\n"
        f"{json.dumps(listed, ensure_ascii=False)}\n\nDESCRIPTION:\n{description}"
    )


_FENCE = re.compile(r"^```[a-zA-Z]*\n(?P<body>.*)\n```$", re.S)


def clean_text(answer: str) -> str:
    """The model's Markdown, without a fence around all of it; headings below the report's."""

    text = (answer or "").strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group("body").strip()
    # A level-1 heading would compete with the report's own title.
    return re.sub(r"(?m)^# ", "## ", text)


def read_scope(answer: str, known: set[str]) -> dict[str, Any]:
    """The model's proposed pick, kept to real asset ids and analyses."""

    text = clean_text(answer)
    start, end = text.find("{"), text.rfind("}")
    try:
        found = json.loads(text[start : end + 1]) if start >= 0 else {}
    except ValueError:
        found = {}
    ids = [str(a) for a in found.get("asset_ids") or [] if str(a) in known]
    analyses = [a for a in found.get("analyses") or [] if a in ANALYSES]
    return {
        "asset_ids": list(dict.fromkeys(ids))[:MAX_ASSETS],
        "analyses": analyses or ["loops"],
        "why": str(found.get("why") or "")[:500],
        "dropped": [str(a) for a in found.get("asset_ids") or [] if str(a) not in known],
    }


# Plant tags as ISA 5.1 writes them (FIC-1003, PT-101A): what a model must not invent.
TAG = re.compile(r"\b[A-Z]{1,4}-\d{2,5}[A-Z]?\b")


def ungrounded(text: str, facts: dict[str, Any]) -> list[str]:
    """The tags the text names that the facts never name (a model inventing an asset)."""

    given = set(TAG.findall(json.dumps(facts, ensure_ascii=False, default=str)))
    return sorted(set(TAG.findall(text)) - given)


def requirement_problems(requirements: str) -> list[str]:
    """What a proposal of requirements says about this period's data instead of how to write:
    the tags it names (a small model copied facts into the prompt, 2026-10-31)."""

    tags = sorted(set(TAG.findall(requirements)))
    if not tags:
        return []
    return [
        t(
            "The proposal names {tags}: requirements say how to write, not what the data is.",
            tags=", ".join(tags[:8]),
        )
    ]


def section_text(title: str, body: str, facts: dict[str, Any], model: str = "") -> str:
    """The cell the report keeps: the title as its heading, the model's text, and a line saying
    it was written by a model from N facts (so a reader knows what they read)."""

    heading = f"# {title.strip()}\n\n" if title.strip() else ""
    invented = ungrounded(body, facts)
    warning = (
        "\n\n> "
        + t(
            "Check: the text names {tags}, which the facts it was given do not.",
            tags=", ".join(invented[:10]),
        )
        if invented
        else ""
    )
    counted = t(
        "Written by a language model{model} from {results} results and {events} events of "
        "{assets} assets. Check before acting.",
        model=f" ({model})" if model else "",
        results=len(facts.get("results") or []),
        events=facts.get("events_total", len(facts.get("events") or [])),
        assets=len(facts.get("assets") or []),
    )
    return f"{heading}{body.strip()}{warning}\n\n*{counted}*\n"
