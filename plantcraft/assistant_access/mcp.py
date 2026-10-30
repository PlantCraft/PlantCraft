"""The read-only MCP server: an AI assistant reads the plant through API v1, as its person.

It speaks the Model Context Protocol over Streamable HTTP (``POST /mcp``, JSON-RPC 2.0, one JSON
answer per request, no session and no server-sent stream). Each tool is one read of API v1
(``docs/api-v1.md``): assets, asset types, signals, series, the apps' results (loop health,
alarms), events, runs, follow-up actions and the knowledge texts. A call runs the v1 route inside
this process with a token issued for the person who owns the access token, so the assistant
sees exactly what that person sees, nothing writes, and nothing leaves the internal network
unless the person's assistant is outside it.

The protocol part is small and hand-written on purpose: no new dependency in the offline
wheelhouse, and only ``initialize``, ``ping``, ``tools/list`` and ``tools/call`` are needed.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
# A tool's answer is cut beyond this many characters (an assistant's context is finite).
MAX_TEXT = 60_000
MAX_LIST = 200
# Points per signal a read_series answer aims at when no step is given.
TARGET_POINTS = 1_000
# The most points one history read may ask for (signals × steps): an assistant reads trends, not
# raw archives; a bigger read is refused with the step that fits (owner, 2026-10-23: no question
# may load the plant's whole history).
MAX_READ_POINTS = 20_000
MAX_SERIES = 20
# A list route answers in pages (``X-Next-Cursor``): a tool reads this many before it says the
# list goes on (2026-10-27: 1,000 bench loops filled the first 5,000 results and hid the plant).
MAX_PAGES = 10
NEXT_CURSOR = "X-Next-Cursor"
TRUNCATED = (
    "This list goes on past what was read: narrow it by app, kind or subject before drawing a "
    "conclusion from it."
)


class Paged(list):
    """A list read from several pages; ``truncated`` when more were left after ``MAX_PAGES``."""

    truncated = False


async def _get(client: httpx.AsyncClient, path: str, values: dict[str, Any]) -> httpx.Response:
    """``GET`` ``path``; a list answer in pages is read page by page into one ``Paged`` list,
    kept on the answer as ``paged``."""

    response = await client.get(path, params=values)
    cursor = response.headers.get(NEXT_CURSOR)
    if response.status_code >= 400 or not cursor:
        return response
    try:
        items = Paged(response.json())
    except ValueError:
        return response
    for _ in range(MAX_PAGES - 1):
        page = await client.get(path, params={**values, "cursor": cursor})
        if page.status_code >= 400:
            break
        items.extend(page.json() or [])
        cursor = page.headers.get(NEXT_CURSOR)
        if not cursor:
            break
    items.truncated = bool(cursor)
    response.paged = items  # type: ignore[attr-defined]
    return response


def _payload(response: httpx.Response) -> Any:
    paged = getattr(response, "paged", None)
    if paged is not None:
        return paged
    return response.json()


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

INSTRUCTIONS = (
    "PlantCraft is an open, offline suite of industrial software for process plants. This "
    "server is read-only: it lists the plant's assets (units, equipment, control loops), its "
    "signals and their history, the results the apps publish (Link's loop health, Alarms' "
    "alarms), events, runs and follow-up actions, as the signed-in person may see them. Signal "
    "ids are '<source>:<tag>'; asset references are 'asset:<id>'. Start with search_assets or "
    "search_signals, then read what you need. The apps' own objects (Link's blocks and "
    "algorithms, Models' models, Alarms' alarms, View's dashboards and reports) are listed with "
    "list_app_objects; which alarms "
    "are active now is Alarms' alarm list (where active=true), not older results. Signals "
    "with problems (frozen, no data, bad quality) are Link's signal_quality results; a result "
    "marked stale means its app stopped publishing it: say so rather than read it as ok. Give a value "
    "with the unit "
    "its signal has. Never claim a value you did not read."
)


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    # (method, path, query or body) for the v1 call, from the checked arguments.
    request: Callable[[dict[str, Any]], tuple[str, str, dict[str, Any]]] = lambda _a: (
        "GET",
        "",
        {},
    )
    # Optional local step on the v1 answer (filtering, trimming).
    shape: Callable[[Any, dict[str, Any]], Any] | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }


def _text(description: str, max_length: int = 400) -> dict[str, Any]:
    return {"type": "string", "description": description, "maxLength": max_length}


def _limit(default: int = 50) -> dict[str, Any]:
    return {"type": "integer", "minimum": 1, "maximum": MAX_LIST, "default": default}


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


# The names people and models give the suite's apps, by app id: their screen names (Link is
# Analytics, Dashboards is View since 2026-10-26) and the ids they had before.
APP_WORDS = {
    "linkcraft": ("link", "analytics", "cpm", "cpmcraft", "datacraft", "twincraft"),
    "dashcraft": ("view", "dashboards", "dashboard", "trendcraft"),
    "modelcraft": ("models", "model"),
    "alarmcraft": ("alarms", "alarm"),
    "histcraft": ("historian", "history"),
    "doccraft": ("documents", "document"),
    "simcraft": ("simulator",),
    "processcraft": ("desk", "platform"),
}


def app_id(name: str) -> str:
    """The app's id from its id, its name or a former id: a small model asked for app "models"
    and got a 404 (2026-10-26)."""

    wanted = re.sub(r"[^a-z]", "", name.lower())
    for known, words in APP_WORDS.items():
        if wanted == known or wanted in words:
            return known
    return name.strip()


def _app(args: dict[str, Any]) -> str | None:
    return app_id(args["app"]) if args.get("app") else None


def _drop_empty(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", [])}


def _matching_assets(items: Any, args: dict[str, Any]) -> Any:
    query = str(args.get("query") or "").strip().lower()
    if query and isinstance(items, list):
        items = [
            item
            for item in items
            if query in str(item.get("name", "")).lower()
            or query in str(item.get("id", "")).lower()
        ]
    kind = args.get("type") or args.get("kind")
    if kind and items == []:
        # "How many control loops": kind=control_loop found none and was said as 0 (round 6).
        return {
            "total": 0,
            "items": [],
            "note": f"no asset of type '{kind}': list_asset_types gives the type ids",
        }
    return _cut(items, int(args.get("limit") or 50))


def _first(items: Any, args: dict[str, Any]) -> Any:
    return _cut(items, int(args.get("limit") or 50))


def _results(items: Any, args: dict[str, Any]) -> Any:
    """The latest results; stale ones are said apart, as an app that stopped publishing (round
    4: Link's stale signal quality was read as "nothing is frozen")."""

    shaped = _cut(items, int(args.get("limit") or 50))
    stale = [item for item in items if item.get("stale")] if isinstance(items, list) else []
    if not stale:
        return shaped
    newest = max(str(item.get("at") or "") for item in stale)
    note = (
        f"{len(stale)} of {len(items)} results are stale (the newest of them from {newest}): "
        "their app stopped publishing them, so they say nothing about now"
    )
    if isinstance(shaped, dict):
        return {**shaped, "note": f"{shaped['note']}; {note}"}
    return {"total": len(items), "items": shaped, "note": note}


def _owned(payload: Any, args: dict[str, Any]) -> Any:
    """The actions one person owns, when asked: others' were listed as "yours" (round 6)."""

    owner = str(args.get("owner") or "").strip().lower()
    if not owner or not isinstance(payload, dict):
        return payload
    items = [
        item for item in payload.get("items") or [] if str(item.get("owner") or "").lower() == owner
    ]
    limit = int(args.get("limit") or 50)
    note = f"{len(items)} owned by {owner}" if items else f"none is owned by {owner}"
    return {**payload, "items": items[:limit], "total": len(items), "note": note}


def _cut(items: Any, limit: int) -> Any:
    """The first ``limit`` items; a list that had more says how many it had, so an answer can
    count them (a list cut at 30 of 71 was read as 30, 2026-10-26)."""

    if not isinstance(items, list) or len(items) <= limit:
        return items
    return {"total": len(items), "items": items[:limit], "note": f"first {limit} of {len(items)}"}


def _counted(rows: Any) -> Any:
    """Results counted per group and status, the groups with most problems first."""

    if not isinstance(rows, list):
        return rows
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = row.get("group") or {"id": "", "name": "(not under one)"}
        entry = groups.setdefault(
            group["id"], {"id": group["id"], "name": group["name"], "total": 0, "status": {}}
        )
        entry["total"] += 1
        if row.get("stale"):
            entry["stale"] = entry.get("stale", 0) + 1
        status = str(row.get("status") or "unknown")
        entry["status"][status] = entry["status"].get(status, 0) + 1

    def problems(entry: dict[str, Any]) -> int:
        return entry["status"].get("alarm", 0) + entry["status"].get("warning", 0)

    ordered = sorted(groups.values(), key=lambda entry: (-problems(entry), entry["name"]))
    for entry in ordered:
        entry["problems"] = problems(entry)
    return {"results": len(rows), "groups": ordered}


OBJECT_FIELD = 300


def _objects(payload: Any, args: dict[str, Any]) -> Any:
    """An app's objects, found by words of the id, name or description, without long fields
    (code, docs): read one with get_app_object."""

    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return payload
    query = str(args.get("query") or "").strip().lower()
    if query:
        items = [item for item in items if query in json.dumps(item, ensure_ascii=False).lower()]
    # "active=true, priority=high": fields equal to these values (Alarms' active alarms).
    for part in str(args.get("where") or "").split(","):
        key, _, wanted = part.partition("=")
        if key.strip() and wanted.strip():
            items = [
                item
                for item in items
                if isinstance(item, dict)
                and str(item.get(key.strip())).lower() == wanted.strip().lower()
            ]
    short = [
        {
            key: value
            for key, value in item.items()
            if not isinstance(value, (dict, list)) and len(str(value)) <= OBJECT_FIELD
        }
        for item in items
        if isinstance(item, dict)
    ]
    found = _cut(short, int(args.get("limit") or 100))
    return found if isinstance(found, dict) else {"total": len(short), "items": short}


def _finest_step(args: dict[str, Any]) -> int:
    """The smallest step a read of these signals over this period may ask for."""

    end = _when(args.get("end")) or datetime.now(timezone.utc)
    start = _when(args.get("start")) or end - timedelta(hours=24)
    signals = len(list(args["signal_ids"])[:MAX_SERIES])
    return max(1, math.ceil(signals * max(1.0, (end - start).total_seconds()) / MAX_READ_POINTS))


def _series_stats(payload: Any) -> Any:
    """Each series as its statistics (the min and max with the time they were reached)."""

    if not isinstance(payload, dict):
        return payload
    stats = []
    for item in payload.get("series") or []:
        pairs = [
            (stamp, float(value))
            for stamp, value in zip(item.get("t") or [], item.get("v") or [], strict=False)
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ]
        entry: dict[str, Any] = {"signal": item.get("signal"), "unit": item.get("unit") or ""}
        if pairs:
            low = min(pairs, key=lambda pair: pair[1])
            high = max(pairs, key=lambda pair: pair[1])
            entry |= {
                "count": len(pairs),
                "mean": round(sum(value for _, value in pairs) / len(pairs), 6),
                "min": low[1],
                "min_at": low[0],
                "max": high[1],
                "max_at": high[0],
                "first": pairs[0][1],
                "last": pairs[-1][1],
            }
        else:
            entry["count"] = 0
        stats.append(entry)
    return {**{k: v for k, v in payload.items() if k != "series"}, "series": stats}


def _series_body(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    end = _when(args.get("end")) or datetime.now(timezone.utc)
    start = _when(args.get("start")) or end - timedelta(hours=24)
    if end <= start:
        raise ValueError("end must be after start")
    step = args.get("step_seconds")
    seconds = (end - start).total_seconds()
    if not step:
        step = max(1, math.ceil(seconds / TARGET_POINTS))
    signals = len(list(args["signal_ids"])[:MAX_SERIES])
    points = signals * seconds / int(step)
    if points > MAX_READ_POINTS:
        fits = math.ceil(signals * seconds / MAX_READ_POINTS)
        raise ValueError(
            f"this read asks for about {int(points):,} points (at most {MAX_READ_POINTS:,}): "
            f"use step_seconds of {fits} or more, fewer signals or a shorter period"
        )
    return (
        "POST",
        "/api/v1/series",
        {
            "signals": list(args["signal_ids"])[:MAX_SERIES],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": int(step),
        },
    )


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


TOOLS: tuple[Tool, ...] = (
    Tool(
        "whoami",
        "Who am I",
        "The person this assistant reads as: user name, name, access level and apps.",
        request=lambda _a: ("GET", "/api/v1/me", {}),
    ),
    Tool(
        "list_apps",
        "Installed apps",
        "The apps of the suite installed here (Link, Historian, Dashboards, Alarms...) that the "
        "person may open.",
        request=lambda _a: ("GET", "/api/v1/apps", {}),
    ),
    Tool(
        "search_assets",
        "Search assets",
        "Assets of the plant tree (sites, units, areas, equipment, control loops), each with its "
        "signals by role and its relations. Filter by words in the name or id, by type (kind, "
        "e.g. 'loop' or 'equipment', with its subtypes: equipment finds pumps and vessels too), "
        "or by parent. The answer says its total when it lists more than the limit.",
        {
            "query": _text("Words of the name or id.", 200),
            "kind": _text("Asset type with its subtypes, e.g. loop, equipment, unit.", 60),
            "type": _text("Same as kind.", 64),
            "parent_id": _text("Only the children of this asset.", 200),
            "limit": _limit(),
        },
        request=lambda a: (
            "GET",
            "/api/v1/assets",
            _drop_empty(
                # An exact kind found no equipment: the plant's are pumps, vessels... (2026-10-26).
                {"type": a.get("type") or a.get("kind"), "parent_id": a.get("parent_id")}
            ),
        ),
        shape=_matching_assets,
    ),
    Tool(
        "get_asset",
        "Read an asset",
        "One asset: its type, attributes, signals by role and relations.",
        {"asset_id": _text("The asset's id.", 200)},
        ("asset_id",),
        request=lambda a: ("GET", f"/api/v1/assets/{_quote(a['asset_id'])}", {}),
    ),
    Tool(
        "list_asset_types",
        "Asset types",
        "The type catalog: each type's attributes and the signal roles the apps read.",
        request=lambda _a: ("GET", "/api/v1/asset-types", {}),
    ),
    Tool(
        "search_signals",
        "Search signals",
        "Signals (tags) by words of the id, name or description: id '<source>:<tag>', unit, "
        "limits and source type.",
        {"query": _text("Words to find, e.g. FIC-101 or temperature.", 200), "limit": _limit()},
        request=lambda a: ("GET", "/api/v1/signals", _drop_empty({"q": a.get("query")})),
        shape=_first,
    ),
    Tool(
        "get_signal",
        "Read a signal",
        "One signal's description: name, unit, limits, source.",
        {"signal_id": _text("The signal id, '<source>:<tag>'.")},
        ("signal_id",),
        request=lambda a: ("GET", f"/api/v1/signals/{_quote(a['signal_id'])}", {}),
    ),
    Tool(
        "signal_value",
        "Signal value",
        "One number about a signal over a recent window: last, mean, min, max or std.",
        {
            "signal_id": _text("The signal id, '<source>:<tag>'."),
            "agg": {
                "type": "string",
                "enum": ["last", "mean", "min", "max", "std"],
                "default": "last",
            },
            "window": _text("Window like 1h, 24h or 7d.", 10),
        },
        ("signal_id",),
        request=lambda a: (
            "GET",
            f"/api/v1/signals/{_quote(a['signal_id'])}/value",
            _drop_empty({"agg": a.get("agg") or "last", "window": a.get("window") or "1h"}),
        ),
    ),
    Tool(
        "signal_stats",
        "Statistics of a period",
        f"Exact statistics of up to {MAX_SERIES} signals between two times (ISO 8601; default: "
        "the last 24 h): count, mean, min and max with their times, first and last value. Use "
        "it for a period's mean, min or max (yesterday, last week): it reads every point the "
        "history keeps, where read_series averages them.",
        {
            "signal_ids": {
                "type": "array",
                "items": {"type": "string", "maxLength": 400},
                "minItems": 1,
                "maxItems": MAX_SERIES,
            },
            "start": _text("Start time, ISO 8601.", 40),
            "end": _text("End time, ISO 8601.", 40),
        },
        ("signal_ids",),
        request=lambda a: _series_body({**a, "step_seconds": _finest_step(a)}),
        shape=lambda payload, _a: _series_stats(payload),
    ),
    Tool(
        "read_series",
        "Read history",
        f"The history of up to {MAX_SERIES} signals between two times (ISO 8601; default: the "
        f"last 24 h), as times and values. Without a step the answer has about {TARGET_POINTS} "
        "points per signal, each an average over its step: for a period's exact mean, min or "
        "max use signal_stats.",
        {
            "signal_ids": {
                "type": "array",
                "items": {"type": "string", "maxLength": 400},
                "minItems": 1,
                "maxItems": MAX_SERIES,
            },
            "start": _text("Start time, ISO 8601.", 40),
            "end": _text("End time, ISO 8601.", 40),
            "step_seconds": {"type": "integer", "minimum": 1, "maximum": 86_400},
        },
        ("signal_ids",),
        request=_series_body,
    ),
    Tool(
        "latest_results",
        "Latest results",
        "The latest result each app published about assets and signals: Link's loop health and "
        "signal quality, Alarms' alarm states, and others, with status (ok, warning, alarm, "
        "unknown), score and summary. Filter by subject ('asset:<id>' or a signal id), app, kind, "
        "and 'under' (an asset id: only results about it and the assets under it, e.g. one unit).",
        {
            "subject": _text("asset:<id> or a signal id."),
            "app": _text("App id, e.g. linkcraft or alarmcraft.", 40),
            "kind": _text("Result kind, e.g. loop_health.", 60),
            "under": _text("Asset id: only results about it and the assets under it."),
            "limit": _limit(),
        },
        request=lambda a: (
            "GET",
            "/api/v1/results",
            _drop_empty(
                {
                    "subject": a.get("subject"),
                    "app": _app(a),
                    "kind": a.get("kind"),
                    "under": a.get("under"),
                }
            ),
        ),
        shape=_results,
    ),
    Tool(
        "count_results",
        "Count results by unit",
        "How many latest results each unit (or other asset type) has, by status (ok, warning, "
        "alarm, unknown), most problems first. Use it for 'which unit has most loops with "
        "problems' or 'how is each area doing'; filter by app and kind (e.g. linkcraft, "
        "loop_health). Then latest_results with 'under' lists one unit's results. 'stale' "
        "counts results past their expiry: the app stopped publishing them, so say so.",
        {
            "group": _text("Asset type to count by: unit (default), area, site or equipment.", 60),
            "app": _text("App id, e.g. linkcraft or alarmcraft.", 40),
            "kind": _text("Result kind, e.g. loop_health.", 60),
        },
        request=lambda a: (
            "GET",
            "/api/v1/results",
            _drop_empty({"group": a.get("group") or "unit", "app": _app(a), "kind": a.get("kind")}),
        ),
        shape=lambda rows, _a: _counted(rows),
    ),
    Tool(
        "result_history",
        "Result history",
        "How one subject's results changed over the last 90 days, oldest first.",
        {
            "subject": _text("asset:<id> or a signal id."),
            "app": _text("App id.", 40),
            "kind": _text("Result kind.", 60),
            "limit": _limit(100),
        },
        ("subject",),
        request=lambda a: (
            "GET",
            "/api/v1/results/history",
            _drop_empty(
                {
                    "subject": a.get("subject"),
                    "app": a.get("app"),
                    "kind": a.get("kind"),
                    "limit": a.get("limit") or 100,
                }
            ),
        ),
    ),
    Tool(
        "recent_events",
        "Recent events",
        "What happened, oldest first: findings, alarms raised and cleared, imports, runs. "
        "Filter by reference ('asset:<id>') and kind (e.g. alarmcraft.alarm).",
        {
            "ref": _text("asset:<id> or another reference."),
            "kind": _text("Event kind.", 120),
            "limit": _limit(),
        },
        request=lambda a: (
            "GET",
            "/api/v1/events",
            _drop_empty(
                {"ref": a.get("ref"), "kind": a.get("kind"), "limit": a.get("limit") or 50}
            ),
        ),
    ),
    Tool(
        "list_runs",
        "Runs",
        "The apps' runs (rounds, analyses, simulations), newest first.",
        {
            "app": _text("App id.", 40),
            "status": {
                "type": "string",
                "enum": ["queued", "running", "done", "failed", "cancelled"],
            },
            "subject": _text("asset:<id> or a signal id."),
            "limit": _limit(),
        },
        request=lambda a: (
            "GET",
            "/api/v1/runs",
            _drop_empty(
                {
                    "app": a.get("app"),
                    "status": a.get("status"),
                    "subject": a.get("subject"),
                    "limit": a.get("limit") or 50,
                }
            ),
        ),
    ),
    Tool(
        "list_actions",
        "Follow-up actions",
        "The follow-up actions this person sees (all of them without ref): title, owner, "
        "status, due date. Filter by asset ('asset:<id>') or status: open ones are open, "
        "in_progress and blocked; cancelled is shown as Archived. Each says whether it is "
        "overdue (overdue: true): use that field, never work it out from the dates. For "
        "'my actions' give owner: the person's user name; an empty list means none is theirs.",
        {
            "ref": _text("asset:<id>, optional."),
            "status": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["open", "in_progress", "blocked", "done", "cancelled"],
                },
            },
            "owner": _text(
                "A user name: only the actions they own (the person's own: theirs).", 60
            ),
            "limit": _limit(),
        },
        request=lambda a: (
            "GET",
            "/api/v1/actions",
            _drop_empty(
                {
                    "ref": a.get("ref"),
                    "status": a.get("status"),
                    "limit": 500 if a.get("owner") else a.get("limit") or 50,
                }
            ),
        ),
        shape=_owned,
    ),
    Tool(
        "search_knowledge",
        "Search the apps' explanations",
        "Texts the apps wrote for assistants: how an algorithm or a block works, a run's report. "
        "Give a reference ('algorithm:linkcraft/loop_health') or words.",
        {
            "ref": _text("A reference."),
            "query": _text("Words to find.", 200),
            "app": _text("App id.", 40),
            "limit": _limit(20),
        },
        request=lambda a: (
            "GET",
            "/api/v1/knowledge",
            _drop_empty(
                {
                    "ref": a.get("ref"),
                    "q": a.get("query"),
                    "app": a.get("app"),
                    "limit": a.get("limit") or 20,
                }
            ),
        ),
    ),
    Tool(
        "list_object_kinds",
        "The apps' objects",
        "What each app keeps that can be listed: Link's blocks and algorithms, Models' models and "
        "studies... (app id and kind for list_app_objects).",
        request=lambda _a: ("GET", "/api/v1/objects", {}),
    ),
    Tool(
        "list_app_objects",
        "List an app's objects",
        "All of one app's objects of one kind, with their total, found by words or by fields: "
        "Link's blocks and algorithms (app linkcraft, kind block or algorithm), Alarms' alarms "
        "as they are now (app alarmcraft, kind alarm, where active=true for the active ones; "
        "a rule's enabled says it runs, its alarms how many of its alarms exist), View's "
        "dashboards and reports with their panels' signals (app dashcraft, kind dashboard or "
        "report). Count from total.",
        {
            "app": _text("App id, e.g. linkcraft.", 40),
            "kind": _text("Kind, from list_object_kinds, e.g. block.", 40),
            "query": _text("Words to find.", 200),
            "where": _text("Fields equal to values, e.g. active=true, priority=high.", 200),
            "limit": _limit(100),
        },
        ("app", "kind"),
        request=lambda a: (
            "GET",
            f"/api/v1/apps/{_quote(app_id(a['app']))}/objects/{_quote(a['kind'])}",
            {},
        ),
        shape=_objects,
    ),
    Tool(
        "get_app_object",
        "Read an app's object",
        "One of an app's objects, whole: a block's ports, parameters, docs and code; an "
        "algorithm's diagram.",
        {
            "app": _text("App id.", 40),
            "kind": _text("Kind.", 40),
            "object_id": _text("The object's id, from list_app_objects.", 200),
        },
        ("app", "kind", "object_id"),
        request=lambda a: (
            "GET",
            f"/api/v1/apps/{_quote(app_id(a['app']))}/objects/{_quote(a['kind'])}/"
            f"{_quote(a['object_id'])}",
            {},
        ),
    ),
)
BY_NAME = {tool.name: tool for tool in TOOLS}


class InvalidArguments(ValueError):
    pass


def check_arguments(tool: Tool, arguments: Any) -> dict[str, Any]:
    """The arguments as the tool's schema allows them; anything else is refused."""

    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise InvalidArguments("arguments must be an object")
    unknown = set(arguments) - set(tool.properties)
    if unknown:
        raise InvalidArguments(f"unknown arguments: {', '.join(sorted(unknown))}")
    missing = [name for name in tool.required if arguments.get(name) in (None, "", [])]
    if missing:
        raise InvalidArguments(f"missing arguments: {', '.join(missing)}")
    checked: dict[str, Any] = {}
    for name, value in arguments.items():
        spec = tool.properties[name]
        kind = spec.get("type")
        if value is None:
            continue
        if kind == "string":
            if not isinstance(value, str) or len(value) > spec.get("maxLength", 400):
                raise InvalidArguments(f"{name} must be a short text")
            if "enum" in spec and value not in spec["enum"]:
                raise InvalidArguments(f"{name} must be one of {', '.join(spec['enum'])}")
        elif kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidArguments(f"{name} must be a whole number")
            if not spec.get("minimum", value) <= value <= spec.get("maximum", value):
                raise InvalidArguments(f"{name} is out of range")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise InvalidArguments(f"{name} must be true or false")
        elif kind == "array":
            if (
                not isinstance(value, list)
                or not value
                or len(value) > spec.get("maxItems", MAX_LIST)
                or not all(isinstance(item, str) and 0 < len(item) <= 400 for item in value)
            ):
                raise InvalidArguments(f"{name} must be a list of ids")
        checked[name] = value
    for name in ("start", "end"):
        if name in checked:
            try:
                _when(checked[name])
            except ValueError as exc:
                raise InvalidArguments(f"{name} must be an ISO 8601 time") from exc
    return checked


def only_apps(payload: Any, apps: set[str] | None) -> Any:
    """``payload`` without what apps the person may not open published (results, events,
    runs, knowledge texts: any item with an ``app``). ``None`` keeps everything."""

    if apps is None:
        return payload
    if isinstance(payload, list):
        return [
            only_apps(item, apps)
            for item in payload
            if not (
                isinstance(item, dict)
                and isinstance(item.get("app"), str)
                and item["app"] not in apps
            )
        ]
    if isinstance(payload, dict):
        return {key: only_apps(value, apps) for key, value in payload.items()}
    return payload


def _clip(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= MAX_TEXT:
        return text
    return text[:MAX_TEXT] + f"\n[cut: {len(text) - MAX_TEXT} more characters; narrow the query]"


async def call_tool(
    client: httpx.AsyncClient,
    tool: Tool,
    arguments: dict[str, Any],
    apps: set[str] | None = None,
) -> dict[str, Any]:
    """Run one tool against API v1 with ``client`` (which carries the person's token); with
    ``apps``, only what those apps published comes back (``only_apps``)."""

    try:
        method, path, values = tool.request(arguments)
    except ValueError as exc:  # a read refused before it is made (a period too long, …)
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    if method == "POST":
        response = await client.post(path, json=values)
    else:
        response = await _get(client, path, values)
    try:
        payload = _payload(response)
    except ValueError:
        payload = {"detail": response.text[:500]}
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        return {
            "content": [{"type": "text", "text": f"HTTP {response.status_code}: {_clip(detail)}"}],
            "isError": True,
        }
    truncated = getattr(payload, "truncated", False)
    payload = only_apps(payload, apps)
    if tool.shape is not None:
        payload = tool.shape(payload, arguments)
    if truncated:
        payload = {"note": TRUNCATED, "answer": payload}
    return {"content": [{"type": "text", "text": _clip(payload)}], "isError": False}


async def call_in_process(
    app: Any, token: str, tool: Tool, arguments: dict[str, Any], apps: set[str] | None = None
) -> dict[str, Any]:
    """Run one tool against this process's own API v1 (an ASGI call, never the network)."""

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://processcraft.internal",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    ) as client:
        return await call_tool(client, tool, arguments, apps)


async def request_in_process(
    app: Any, token: str, method: str, path: str, values: dict[str, Any]
) -> tuple[int, Any]:
    """One request to this process's own API v1 (an ASGI call, never the network): the status and
    the JSON answer. Desk's Assistant reads the plant through it."""

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://processcraft.internal",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    ) as client:
        if method == "POST":
            response = await client.post(path, json=values)
        else:
            response = await _get(client, path, values)
        try:
            return response.status_code, _payload(response)
        except ValueError:
            return response.status_code, {"detail": response.text[:500]}


def result(request_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def initialize(params: Any, version: str) -> dict[str, Any]:
    asked = params.get("protocolVersion") if isinstance(params, dict) else None
    chosen = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": chosen,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": "processcraft",
            "title": "PlantCraft (read-only)",
            "version": version,
        },
        "instructions": INSTRUCTIONS,
    }
