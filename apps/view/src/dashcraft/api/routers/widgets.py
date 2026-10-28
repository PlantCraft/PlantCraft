"""View's widgets: declared in ``app.toml`` (``[[contributes.widgets]]``), drawn on View's
Overview and on Desk's Today alike (PlantCraft ``docs/widgets.md``). Links are paths on this
host, under View's prefix."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk import widgets as w

from dashcraft.api.deps import CurrentUser, RuntimeDep, permissions
from dashcraft.i18n import t
from dashcraft.meta import FILES
from dashcraft.reports.schedule import zone

router = APIRouter(prefix="/api/widgets", tags=["widgets"])

WEEKDAYS_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _next_send(rt: Any, report: dict[str, Any]) -> str:
    """When the report goes out next, on the plant's clock (the one its schedule is set on):
    "Next: today 08:00", "Next: Mon 08:00" within the week, "Next: 03 Nov 08:00" after it."""

    try:
        at = datetime.fromisoformat(str(report.get("next_run_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return t("Not scheduled")
    at = at if at.tzinfo else at.replace(tzinfo=UTC)
    service = rt.report_service
    where = zone(service.zone())
    now = service.clock().astimezone(where)
    local = at.astimezone(where)
    if local <= now:
        return t("Next: due now")
    days = (local.date() - now.date()).days
    if days == 0:
        day = t("today")
    elif days < 7:
        day = t(WEEKDAYS_SHORT[local.weekday()])
    else:
        day = local.strftime("%d %b")
    return t("Next: {day} {at}", day=day, at=local.strftime("%H:%M"))


def _updated(entry: dict[str, Any]) -> str | None:
    """The line under a dashboard's, trend's or display's name: when it last changed, said as
    such ("Updated 5 h ago"), the way a report's line says when it goes out next."""

    when = w.ago(entry.get("updated_at"), t)
    return t("Updated {when}", when=when) if when else None


def _public_links(rt: Any, user: Any, root: str) -> dict[str, Any]:
    """The links that open a dashboard, report or process display without signing in, of the
    things this person sees, newest first: what each opens and when it was last opened."""

    perms = permissions(rt, user)
    things: dict[tuple[str, str], tuple[str, str, str]] = {}
    for entry in rt.dashboards.list():
        if perms.sees(entry):
            key = ("dashboard", entry["dashboard_id"])
            things[key] = (entry["name"], t("Dashboard"), f"{root}/d/{quote(key[1], safe='')}")
    for entry in rt.reports.list():
        if perms.sees(entry):
            key = ("report", entry["report_id"])
            things[key] = (entry["name"], t("Report"), f"{root}/reports/{quote(key[1], safe='')}")
    for entry in rt.diagrams.list():
        if perms.sees(entry):
            key = ("diagram", entry["diagram_id"])
            things[key] = (
                entry["name"],
                t("Process display"),
                f"{root}/diagrams/{quote(key[1], safe='')}",
            )
    rows = []
    for share in rt.dashboards.active_shares():
        found = things.get((share.get("target") or "dashboard", share["dashboard_id"]))
        if found is None:
            continue
        name, kind, href = found
        opened = w.ago(share.get("last_used_at"), t)
        rows.append(
            w.item(
                f"{name} · {share['label']}" if share.get("label") else name,
                detail=" · ".join(
                    (kind, t("Opened {when}", when=opened) if opened else t("Never opened"))
                ),
                href=href,
            )
        )
    return w.items(rows[:8], href=f"{root}/dashboards", empty=t("No public link."))


def _run_state(run: dict[str, Any] | None) -> str | None:
    """The last run's state in the suite's words: ok, warning (made, some sections unread),
    alarm (failed), none before the first run."""

    if not run:
        return None
    if run.get("status") == "failed":
        return "alarm"
    return "warning" if run.get("problems") else "ok"


@router.get("")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(FILES.manifest(), t)


def _seen(rt: Any, user: Any) -> list[dict[str, Any]]:
    perms = permissions(rt, user)
    return [item for item in rt.dashboards.list() if perms.sees(item)]


@router.get("/{widget_id}/options")
def widget_options(widget_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    if widget_id == "dashboard":
        return w.options(
            w.option(item["dashboard_id"], item["name"], item.get("description") or None)
            for item in _seen(rt, user)
        )
    raise HTTPException(404, t("Widget not found."))


@router.get("/{widget_id}")
def widget(
    widget_id: str,
    rt: RuntimeDep,
    user: CurrentUser,
    item: str | None = Query(default=None, max_length=100),
) -> dict[str, Any]:
    root = rt.settings.root_path
    if widget_id == "trends":
        return w.items(
            [
                w.item(
                    entry["name"],
                    detail=_updated(entry),
                    href=f"{root}/trends/{quote(entry['trend_id'], safe='')}",
                )
                for entry in rt.trends.list()[:8]
            ],
            href=f"{root}/trends",
            empty=t("No saved trend yet."),
        )
    if widget_id == "reports":
        perms = permissions(rt, user)
        last = rt.reports.last_runs()
        return w.items(
            [
                w.item(
                    entry["name"],
                    detail=_next_send(rt, entry),
                    state=_run_state(last.get(entry["report_id"])),
                    href=f"{root}/reports/{quote(entry['report_id'], safe='')}",
                )
                for entry in rt.reports.list()
                if perms.sees(entry)
            ][:8],
            href=f"{root}/reports",
            empty=t("No report yet."),
        )
    if widget_id == "diagrams":
        perms = permissions(rt, user)
        return w.items(
            [
                w.item(
                    entry["name"],
                    detail=_updated(entry),
                    href=f"{root}/diagrams/{quote(entry['diagram_id'], safe='')}",
                )
                for entry in rt.diagrams.list()
                if perms.sees(entry)
            ][:8],
            href=f"{root}/diagrams",
            empty=t("No process display yet."),
        )
    seen = _seen(rt, user)
    if widget_id == "public-links":
        return _public_links(rt, user, root)
    if widget_id == "dashboards":
        return w.items(
            [
                w.item(
                    entry["name"],
                    detail=_updated(entry),
                    href=f"{root}/d/{quote(entry['dashboard_id'], safe='')}",
                )
                for entry in seen[:8]
            ],
            href=f"{root}/dashboards",
            empty=t("No dashboard yet."),
        )
    if widget_id == "dashboard":
        found = next(
            (entry for entry in seen if entry["dashboard_id"] == item), seen[0] if seen else None
        )
        if found is None:
            return w.facts(None, [], empty=t("No dashboard yet."))
        return w.facts(
            found["name"],
            [
                w.fact(t("Panels"), len(found.get("cards") or [])),
                w.fact(t("Changed"), w.ago(found.get("updated_at"), t) or "—"),
                w.fact(t("Public links"), found.get("public_links") or 0),
                w.fact(t("By"), found.get("updated_by") or found.get("created_by") or "—"),
            ],
            status=t("Open the dashboard"),
            detail=found.get("description") or None,
            href=f"{root}/d/{quote(found['dashboard_id'], safe='')}",
        )
    raise HTTPException(404, t("Widget not found."))
