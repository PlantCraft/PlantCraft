"""HTTP routes: the home page summary (the shell and the launcher) and the settings page."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.api.deps import CurrentUser, Runtime, UserAccess, action_visibility, open_to
from plantcraft.auth.public_demo import DEFAULT_USER, public_demo
from plantcraft.auth.suite import app_access
from plantcraft.db import utc_text
from plantcraft.i18n import t
from plantcraft.platform.datalayer import DataLayerError
from plantcraft_sdk.utc import parse_instant

router = APIRouter()

SOURCE_LABELS = {"opcua": "OPC UA", "pi_web_api": "PI Web API", "csv": "CSV file"}
# More sources than this are counted in the top bar instead of named.
NAMED_SOURCES = 2


def _version() -> str:
    """The installed processcraft version (the user menu's "About")."""
    try:
        return version("plantcraft")
    except PackageNotFoundError:
        return ""


def _source_summary(rt: Any, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """The top bar's source pill: the sources the installation reads data from.

    The scenario's source counts when it has tags or loops (the offline install's empty site
    file does not), by its type (``CSV file``); each added source by its name. ``type`` stays
    the scenario source's type.
    """

    scenario = rt.scenario.source
    names = [
        item["name"] if item["origin"] == "added" else item["type_label"]
        for item in sources
        if item["origin"] == "added" or scenario.tags or rt.scenario.loops or item["routed_signals"]
    ]
    if not names:
        label = t(SOURCE_LABELS.get(scenario.type, scenario.type))
    elif len(names) <= NAMED_SOURCES:
        label = " · ".join(names)
    else:
        label = t("{count} data sources", count=len(names))
    return {"type": scenario.type, "label": label, "names": names}


def _journey(rt: Any, user: str) -> dict[str, Any]:
    """The home page's path (connect, map, watch, act): what the apps did and what is left.

    A few counting queries; the counts of sources, signals and assets are beside it.
    """

    store = rt.workspace.results
    runs = store.runs(limit=1)
    findings = store.status_counts(now=utc_text())
    actions = rt.workspace.actions.counts(action_visibility(rt, user))
    return {
        "last_run": runs[0] if runs else None,
        "schedules": sum(1 for item in store.schedules() if item.get("enabled", True)),
        "findings": {
            app: {status: count for status, count in counts.items() if status != "ok"}
            | {"total": sum(counts.values())}
            for app, counts in findings.items()
        },
        "actions": {
            "open": actions["open"] + actions["in_progress"] + actions["blocked"],
            "overdue": actions["overdue"],
            "done": actions["done"],
            "total": sum(value for key, value in actions.items() if key != "overdue"),
        },
    }


# The home page lists at most this many results that need someone.
ATTENTION_LIMIT = 8


def _attention(
    rt: Any,
    apps: list[Any],
    allowed: dict[str, Any],
    limit: int = ATTENTION_LIMIT,
    scope: Any = None,
) -> list[dict[str, Any]]:
    """The results that need someone, with the subject's name and where to open it.

    An asset opens on its page here (it gathers every app's results); anything else opens where
    the app said (``detail.url``), else on the app's first page. Results of an app the person
    may not open are left out.
    """

    urls = {app.id: app.url for app in apps}
    items = rt.workspace.results.attention(now=utc_text(), limit=4 * limit)
    rows: list[dict[str, Any]] = []
    for item in items:
        if item["app"] in urls and not allowed.get(item["app"]):
            continue
        if scope is not None and not scope.subject(item["subject"]):
            # About an asset out of the person's asset scope (docs/asset-scope.md).
            continue
        if len(rows) == limit:
            break
        kind, _, subject_id = str(item["subject"]).partition(":")
        name = subject_id
        if kind == "asset":
            asset = rt.workspace.assets.get(subject_id)
            name = asset["name"] if asset else subject_id
            url = f"/assets/{subject_id}"
        else:
            if kind == "signal":
                name = subject_id.split(":", 1)[-1]
            url = (item.get("detail") or {}).get("url") or urls.get(item["app"])
        rows.append(
            {
                "app": item["app"],
                "subject": item["subject"],
                "subject_kind": kind,
                "name": name,
                "kind": item["kind"],
                "status": item["status"],
                "score": item["score"],
                "value": item["value"],
                "summary": item["summary"],
                "at": item["at"],
                "url": url,
            }
        )
    return rows


@router.get("/api/home")
def home(user: CurrentUser, access: UserAccess, rt: Runtime) -> dict[str, Any]:
    """What the shell needs on every page: the installation, people, counts and the apps."""

    sources = rt.platform.sources.list()
    apps = rt.suite_apps()
    allowed = app_access(access, apps)
    return {
        "version": _version(),
        # The home page shows the demo tour to visitors of a public demo.
        "public_demo": public_demo() is not None,
        # The demo story is here (`processcraft demo seed` made the visitor account).
        "demo_tour": public_demo() is not None
        or rt.workspace.users.get_user(DEFAULT_USER) is not None,
        "scenario": {
            "name": rt.scenario.name,
            "display_name": rt.scenario.display_name,
            "description": rt.scenario.description,
        },
        "source": _source_summary(rt, sources),
        "users": rt.workspace.users.list_users(kind="person"),
        "counts": {
            "sources": len(sources),
            # Signals in use (the scenario's, the ones added from sources, those on assets),
            # counted without browsing a source.
            "signals": len(
                set(rt.scenario.source.tags)
                | set(rt.platform.sources.routes())
                | set(rt.workspace.assets.signal_assets())
            ),
            "assets": rt.workspace.assets.counts(),
            "users": rt.workspace.counts()["users"],
        },
        "journey": _journey(rt, user),
        # What needs someone now, across the apps (the home page's first list).
        "attention": _attention(rt, apps, allowed, scope=rt.asset_scope(user)),
        # Every installed app, and whether this person may open it (the launcher's cards).
        "apps": [
            {
                "id": app.id,
                "name": app.name,
                "url": app.url,
                "version": app.version,
                "access": allowed.get(app.id),
                # Types it shows at <url>assets/<id>; null when unknown (the app says whether
                # it covers an asset). The asset page links it (docs/app-standard.md, section 2).
                "asset_types": None if app.asset_types is None else list(app.asset_types),
            }
            for app in apps
        ],
    }


# An app whose key reached PlantCraft this recently counts as online (no Docker watch).
SEEN_RECENTLY = timedelta(minutes=15)


def _app_states(rt: Any, apps: list[Any]) -> list[dict[str, Any]]:
    """Each app online, offline or unknown: the suite watch's view of its container when it
    runs (an installation), else whether the app's key reached PlantCraft lately."""

    checks = {item["key"]: item for item in rt.watch.overview().get("checks") or []}
    seen: dict[str, datetime] = {}
    for key in rt.workspace.app_keys.list():
        moment = parse_instant(key.get("last_used_at")) if key.get("active") else None
        if moment and (key["app_id"] not in seen or moment > seen[key["app_id"]]):
            seen[key["app_id"]] = moment
    now = datetime.now(timezone.utc)
    rows = []
    for app in apps:
        check = checks.get(f"service:{app.id}")
        last = seen.get(app.id)
        if check is not None:
            state, detail = ("offline", check["detail"]) if check["bad"] else ("online", "")
        elif last is not None and now - last <= SEEN_RECENTLY:
            state, detail = "online", ""
        else:
            state, detail = "unknown", t("Not seen lately") if last else t("Not seen yet")
        rows.append(
            {
                "id": app.id,
                "name": app.name,
                "url": app.url,
                "state": state,
                "detail": detail,
                "seen_at": last.isoformat() if last else None,
            }
        )
    return rows


UNCONNECTED_SOURCES = frozenset({"derived", "system", "import"})


def _historian(rt: Any) -> dict[str, Any]:
    """The data layer and each source's connection, as the collector last saw it."""

    layer = rt.datalayer
    if not layer.manages_sources:
        sources = rt.platform.sources.list()
        return {
            "kind": "local",
            "ok": True,
            "detail": t("PlantCraft reads its sources itself (no Historian)."),
            "sources": [
                {"id": item["source_id"], "name": item["name"], "type": item["type_label"],
                 "state": "unknown", "detail": ""}
                for item in sources
            ],
        }  # fmt: skip
    try:
        found = layer.sources()
    except DataLayerError as exc:
        return {"kind": "histcraft", "ok": False, "detail": exc.detail, "sources": []}
    rows = []
    for item in found:
        # Series apps write, the suite's own health and files imported once have no connection.
        if item.get("type") in UNCONNECTED_SOURCES:
            continue
        state = item.get("state") or {}
        if not item.get("enabled", True):
            status = "off"
        else:
            status = {"connected": "online", "disconnected": "offline"}.get(
                str(state.get("status") or ""), "unknown"
            )
        rows.append(
            {
                "id": item["source_id"],
                "name": item["name"],
                "type": item["type_label"],
                "state": status,
                "detail": str(state.get("detail") or ""),
            }
        )
    return {"kind": "histcraft", "ok": True, "detail": "", "sources": rows}


@router.get("/api/home/attention")
def attention(
    user: CurrentUser, access: UserAccess, rt: Runtime, limit: int = Query(200, ge=1, le=500)
) -> list[dict[str, Any]]:
    """Everything the apps published that needs someone, worst first (Home's alarms page)."""

    apps = rt.suite_apps()
    return _attention(rt, apps, app_access(access, apps), limit, scope=rt.asset_scope(user))


@router.get("/api/home/status")
def status(_user: CurrentUser, access: UserAccess, rt: Runtime) -> dict[str, Any]:
    """Home's quick status: which apps are online and the Historian's connections."""

    apps = rt.suite_apps()
    allowed = app_access(access, apps)
    return {
        "at": utc_text(),
        "apps": _app_states(rt, [app for app in apps if allowed.get(app.id)]),
        "historian": _historian(rt),
    }


LAYOUT_KEY = "overview.widgets"
WIDGET_ID = r"^[a-z0-9][a-z0-9-]{0,40}(:[a-z0-9][a-z0-9-]{0,40})?$"


class Placement(BaseModel):
    """One widget on the grid (``BoardItem`` in @plantcraft/ui): ``i`` names the placement,
    ``widget`` the catalog id; place and size in grid units (12 columns)."""

    i: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9:~-]+$")
    widget: str = Field(min_length=1, max_length=83)
    x: int = Field(ge=0, le=11)
    y: int = Field(ge=0, le=10_000)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=12)
    title: str | None = Field(default=None, max_length=80)
    config: dict[str, Any] | None = None


class LayoutIn(BaseModel):
    # Widget ids in order (saved before the grid, 2026-10-23), or placements.
    widgets: list[str | Placement] = Field(max_length=40)


PAGE = r"^[a-z0-9][a-z0-9-]{0,40}$"


def _layout_key(page: str | None) -> str:
    """PlantCraft's Overview, or an app's (``page`` is its id: every app's first page is an
    Overview of widgets each person arranges, ``AppOverview`` in @plantcraft/ui)."""

    if page is None or page == "processcraft":
        return LAYOUT_KEY
    if not re.match(PAGE, page):
        raise HTTPException(status_code=422, detail=t("A page name is not valid."))
    return f"{LAYOUT_KEY}:{page}"


@router.get("/api/home/layout")
def layout(user: CurrentUser, rt: Runtime, page: str | None = None) -> dict[str, Any]:
    """The widgets of this person's Overview, in order; null until they arrange their own."""

    return {"widgets": rt.workspace.preferences.get(user, _layout_key(page))}


@router.put("/api/home/layout")
# Each person arranges their own pages, readers too (Desk is everyone's).
@open_to("viewer")
def save_layout(
    body: LayoutIn, user: CurrentUser, rt: Runtime, page: str | None = None
) -> dict[str, Any]:
    key = _layout_key(page)
    widgets: list[Any] = []
    seen: set[str] = set()
    for item in body.widgets:
        widget = item if isinstance(item, str) else item.widget
        if not re.match(WIDGET_ID, widget):
            raise HTTPException(status_code=422, detail=t("A widget id is not valid."))
        name = item if isinstance(item, str) else item.i
        if name in seen:
            continue
        seen.add(name)
        if isinstance(item, str):
            widgets.append(item)
            continue
        placed = item.model_dump(exclude_none=True)
        if len(json.dumps(placed.get("config", {}))) > 4000:
            raise HTTPException(status_code=422, detail=t("A widget's settings are too long."))
        widgets.append(placed)
    rt.workspace.preferences.put(user, key, widgets)
    return {"widgets": widgets}


@router.delete("/api/home/layout")
@open_to("viewer")
def reset_layout(user: CurrentUser, rt: Runtime, page: str | None = None) -> dict[str, Any]:
    """Back to the default widgets."""

    rt.workspace.preferences.delete(user, _layout_key(page))
    return {"widgets": None}
