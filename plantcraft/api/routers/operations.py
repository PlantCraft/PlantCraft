"""HTTP routes: the Operations page (administrators): backups, restores, the drill, updates;
and Health's read-only view for everyone (``/status``).

PlantCraft writes requests and reads answers; the installer and its driver do the work
(``plantcraft.apps.operations_desk``, docs/operations.md). A restore replaces every
database, so it asks for the administrator's password and the backup's name typed again.
Every request is in the audit log.
"""

from __future__ import annotations

import hmac
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from plantcraft.actions import OPEN_STATUSES
from plantcraft.actions.sla import Targets
from plantcraft.api.deps import (
    AdminUser,
    AdminView,
    CurrentUser,
    OperationsView,
    Runtime,
    open_to,
    user_access,
)
from plantcraft.api.identity import issue_user_token
from plantcraft.apps.manager import AppError
from plantcraft.auth.public_demo import public_demo
from plantcraft.auth.support_access import MAX_HOURS as SUPPORT_MAX_HOURS
from plantcraft.config import plant_clock, plant_today
from plantcraft.i18n import t
from plantcraft.platform.datalayer import DataLayerError
from plantcraft_sdk.server import logread
from plantcraft_sdk.utc import parse_instant

router = APIRouter(prefix="/api/operations")


class OperationRequest(BaseModel):
    name: str | None = Field(default=None, max_length=60)


class RestoreRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    typed_name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class Schedule(BaseModel):
    enabled: bool | None = None
    daily_at: str | None = Field(default=None, max_length=5)
    timezone: str | None = Field(default=None, max_length=60)
    drill: bool | None = None
    drill_weekday: int | None = None
    drill_at: str | None = Field(default=None, max_length=5)


def _http(error: AppError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.message)


def _audit(rt: Any, admin: str, action: str, detail: Any = None) -> None:
    rt.workspace.audit.record(admin, action, "suite:operations", detail, app_id="processcraft")


def _password_ok(rt: Any, username: str, password: str) -> bool:
    if not rt.auth.enabled:
        return True  # local use without sign-in: nobody to ask
    if hmac.compare_digest(username, rt.auth.username) and hmac.compare_digest(
        password, rt.auth.password
    ):
        return True
    return rt.workspace.users.verify_password(username, password)


@router.get("")
def overview(_admin: AdminView, rt: Runtime) -> dict[str, Any]:
    """Backups and their checks, the operation running, the history, the last update."""

    return {**rt.operations.overview(), "installer": rt.apps.installer()}


@router.get("/health")
def health(_reader: OperationsView, rt: Runtime) -> dict[str, Any]:
    """The suite watch: what it looked at last, open and recent incidents, Docker's view, the
    machine's load and the load limits (administrators and the Operations role)."""

    return {**rt.watch.overview(), "limits": rt.watch.limits().as_dict()}


class Limits(BaseModel):
    enabled: bool | None = None
    cpu_warning: float | None = None
    cpu_critical: float | None = None
    memory_warning: float | None = None
    memory_critical: float | None = None
    errors_warning: float | None = None
    errors_critical: float | None = None
    minutes: int | None = None


@router.get("/limits")
def limits(_reader: OperationsView, rt: Runtime) -> dict[str, Any]:
    """The load alerts' levels (plantcraft.watch.load)."""

    return rt.watch.limits().as_dict()


@router.put("/limits")
def set_limits(payload: Limits, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Change the load alerts' levels; the next tick of the watch uses them."""

    before = rt.watch.limits().as_dict()
    try:
        value = rt.watch.set_limits(payload.model_dump(exclude_none=True)).as_dict()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _audit(rt, admin, "operations.limits", {"before": before, "after": value})
    return value


# A read of Operations › Logs looks back this far when it names no start.
LOGS_DEFAULT_HOURS = 6
LOGS_MAX_DAYS = 31


@router.get("/logs")
def logs(
    reader: OperationsView,
    rt: Runtime,
    services: str | None = Query(default=None, max_length=500),
    hours: float | None = Query(default=None, gt=0, le=LOGS_MAX_DAYS * 24),
    since: str | None = Query(default=None, max_length=40),
    until: str | None = Query(default=None, max_length=40),
    level: str | None = Query(default=None, max_length=10),
    text: str | None = Query(default=None, max_length=200),
    request_id: str | None = Query(default=None, max_length=64),
    logger: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=logread.DEFAULT_LIMIT, ge=1, le=logread.MAX_LIMIT),
) -> dict[str, Any]:
    """The logs of every server of the suite (or ``services``, comma-separated), newest first,
    with the messages that come back most often. Each read is in the audit log: logs name
    people and what they did. Never to the public demo's visitors: the logs of a public server
    name its visitors' addresses and requests."""

    demo = public_demo()
    if demo is not None and reader == demo.username:
        raise HTTPException(403, t("The public demo does not show its server logs."))

    bounds: dict[str, datetime | None] = {}
    for name, value in (("since", since), ("until", until)):
        moment = parse_instant(value) if value else None
        if value and moment is None:
            raise HTTPException(422, t("Use an ISO 8601 time."))
        bounds[name] = moment
    if bounds["since"] is None:
        back = timedelta(hours=hours if hours is not None else LOGS_DEFAULT_HOURS)
        bounds["since"] = (bounds["until"] or datetime.now(timezone.utc)) - back
    if level and level.upper() not in logread.LEVELS:
        raise HTTPException(422, t("Unknown log level."))
    wanted = [item.strip() for item in (services or "").split(",") if item.strip()] or None
    found = rt.suite_logs.read(
        services=wanted,
        level=level.upper() if level else None,
        text=text,
        request_id=request_id,
        logger=logger,
        limit=limit,
        **bounds,
    )
    _audit(
        rt,
        reader,
        "operations.logs.read",
        {
            key: value
            for key, value in {
                "services": wanted,
                "level": level,
                "text": text,
                "request_id": request_id,
                "logger": logger,
                "since": bounds["since"].isoformat(),
            }.items()
            if value
        },  # fmt: skip
    )
    return found


# What everyone may see of Health: whether each part of the suite runs. The
# disk, the backups, the certificates and the services' resources stay with the administrators.
STATUS_CHECKS = ("service:", "queue:")
SERVICE_FIELDS = ("service", "name", "state", "health", "started_at")


@router.get("/status")
def status(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Health for everyone: each service's state and the open incidents about services."""

    seen = rt.watch.overview()
    services = (seen.get("metrics") or {}).get("services") or []
    return {
        "at": seen.get("at"),
        "watching": bool(seen.get("watching")),
        "held": bool(seen.get("held")),
        "services": [{key: item.get(key) for key in SERVICE_FIELDS} for item in services],
        "open": [
            {key: item.get(key) for key in ("incident_id", "subject", "detail", "opened_at")}
            for item in seen.get("open") or []
            if str(item.get("check_key") or "").startswith(STATUS_CHECKS)
        ],
    }


@router.post("/certificates/{certificate_id}/renew")
def renew_certificate(certificate_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A new client certificate for the Historian's OPC UA connections (the servers must trust
    it again: the answer carries it to download)."""

    issued = issue_user_token(rt, admin)
    if issued is None:
        raise HTTPException(403, t("Only admins change the installation's settings."))
    try:
        renewed = rt.datalayer.renew_certificate(certificate_id, issued["token"])
    except DataLayerError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    _audit(rt, admin, "certificate.renewed", {"id": certificate_id})
    rt.watch.forget_certificates()
    return renewed


@router.put("/schedule")
def set_schedule(payload: Schedule, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    try:
        value = rt.operations.set_schedule(changes)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, "operations.schedule", value)
    return value


@router.post("/restore")
def restore(payload: RestoreRequest, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    if payload.typed_name.strip() != payload.name:
        raise HTTPException(422, t("Type the backup's name exactly to confirm."))
    if not _password_ok(rt, admin, payload.password):
        _audit(rt, admin, "operations.restore.refused", {"name": payload.name})
        raise HTTPException(403, t("Wrong password."))
    try:
        queued = rt.operations.request("restore", admin, name=payload.name)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, "operations.restore", {"name": payload.name, **queued})
    return queued


@router.post("/diagnostics")
def diagnostics(admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Ask the installer for a diagnostic bundle (docs/operations.md, section 4)."""

    queued = rt.operations.request_diagnostics(admin)
    _audit(rt, admin, "operations.diagnostics", queued)
    return queued


@router.get("/diagnostics/{request_id}")
def download_diagnostics(request_id: str, admin: AdminUser, rt: Runtime) -> FileResponse:
    try:
        path = rt.operations.diagnostics_file(request_id)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, "operations.diagnostics.download", {"request_id": request_id})
    name = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"processcraft-diagnostics-{name}.zip",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{action}")
def start(action: str, payload: OperationRequest, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Back up now, check a backup, run the restore drill or apply retention."""

    if action == "restore":
        raise HTTPException(405, t("A restore needs a password confirmation."))
    try:
        queued = rt.operations.request(action, admin, name=payload.name)
    except AppError as exc:
        raise _http(exc) from exc
    _audit(rt, admin, f"operations.{action}", queued)
    return queued


@router.get("/requests/{request_id}")
def outcome(request_id: str, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        return rt.operations.outcome(request_id)
    except AppError as exc:
        raise _http(exc) from exc


# Partners: the companies working at the plant, and the hours they logged ------------------------

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
ENDING_DAYS = 30


def _month_bounds(month: str | None) -> tuple[str, str, str]:
    """``YYYY-MM`` (this month by default) -> (month, first day, last day)."""

    today = date.fromisoformat(plant_today())
    if month:
        first = date.fromisoformat(f"{month}-01")
    else:
        first = today.replace(day=1)
    following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first.strftime("%Y-%m"), first.isoformat(), (following - timedelta(days=1)).isoformat()


def _company_state(company: dict[str, Any], today: str) -> str:
    until = company.get("access_until")
    if not until:
        return "open"
    if until < today:
        return "ended"
    if until <= (date.fromisoformat(today) + timedelta(days=ENDING_DAYS)).isoformat():
        return "ending"
    return "active"


def _entries_by_company(rt: Any, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each time entry with the company of who logged it (None: the plant's own people)."""

    groups = rt.workspace.groups
    companies: dict[str, dict[str, Any] | None] = {}
    for entry in entries:
        name = entry["username"]
        if name not in companies:
            found = groups.companies_of(name)
            companies[name] = found[0] if found else None
        company = companies[name]
        entry["company_id"] = company["group_id"] if company else None
        entry["company_name"] = company["name"] if company else None
    return entries


@router.get("/partners")
def partners(
    _reader: OperationsView,
    rt: Runtime,
    month: str | None = Query(default=None, pattern=MONTH),
) -> dict[str, Any]:
    """Every company (a group of kind ``company``) with its teams, people, sponsor, the end of its
    access, its open requests and the hours its people logged in ``month``."""

    month, first, last = _month_bounds(month)
    today = plant_today()
    groups = rt.workspace.groups
    every = groups.list()
    users = rt.workspace.users
    entries = _entries_by_company(rt, rt.workspace.actions.hours_between(first, last))
    requests = rt.workspace.actions.list(kind="request", statuses=list(OPEN_STATUSES))
    found = []
    for company in (item for item in every if item["kind"] == "company"):
        teams = [
            item
            for item in every
            if item["group_id"] != company["group_id"]
            and (groups.company_of(item["group_id"], every) or {}).get("group_id")
            == company["group_id"]
        ]
        people: dict[str, dict[str, Any]] = {}
        for group in [company, *teams]:
            for member in group["members"]:
                people.setdefault(member["username"], {**member, "teams": [], "coordinator": False})
                if group is not company:
                    people[member["username"]]["teams"].append(group["name"])
        if company["coordinator"] in people:
            people[company["coordinator"]]["coordinator"] = True
        ids = {company["group_id"], *(item["group_id"] for item in teams)}
        mine = [entry for entry in entries if entry["company_id"] == company["group_id"]]
        sponsor = users.get_user(company["sponsor"]) if company.get("sponsor") else None
        found.append(
            {
                "group_id": company["group_id"],
                "name": company["name"],
                "description": company["description"],
                "coordinator": company["coordinator"],
                "coordinator_name": company["coordinator_name"],
                "sponsor": company.get("sponsor"),
                "sponsor_name": (sponsor or {}).get("display_name") or company.get("sponsor"),
                "access_until": company.get("access_until"),
                "state": _company_state(company, today),
                "teams": [
                    {
                        "group_id": item["group_id"],
                        "name": item["name"],
                        "members": len(item["members"]),
                    }
                    for item in teams
                ],
                "people": sorted(people.values(), key=lambda item: item["display_name"].lower()),
                "open_requests": sum(1 for item in requests if item["group_id"] in ids),
                "hours": round(sum(entry["hours"] for entry in mine), 2),
                "billable_hours": round(
                    sum(entry["hours"] for entry in mine if entry["billable"]), 2
                ),
            }
        )
    approvals = rt.workspace.actions.approvals(month)
    for company in found:
        company["approval"] = approvals.get(company["group_id"])
    plant = [entry for entry in entries if entry["company_id"] is None]
    return {
        "month": month,
        "today": today,
        # A month is approved once it has ended (``ActionStore.approve_month``).
        "closable": month < today[:7],
        "companies": found,
        "plant": {
            "hours": round(sum(entry["hours"] for entry in plant), 2),
            "approval": approvals.get(""),
        },
    }


@router.get("/hours")
def hours(
    reader: OperationsView,
    rt: Runtime,
    month: str | None = Query(default=None, pattern=MONTH),
    company: str | None = Query(default=None, max_length=60),
) -> dict[str, Any]:
    """Every time entry of ``month`` with who logged it, the request and their company
    (``company``: one company's; ``plant``: the plant's own people), for the month's report."""

    month, first, last = _month_bounds(month)
    entries = _entries_by_company(rt, rt.workspace.actions.hours_between(first, last))
    if company == "plant":
        entries = [entry for entry in entries if entry["company_id"] is None]
    elif company:
        entries = [entry for entry in entries if entry["company_id"] == company]
    _audit(rt, reader, "operations.hours.read", {"month": month, "company": company})
    return {
        "month": month,
        "first": first,
        "last": last,
        "entries": entries,
        "hours": round(sum(entry["hours"] for entry in entries), 2),
        "billable_hours": round(sum(entry["hours"] for entry in entries if entry["billable"]), 2),
        "approvals": list(rt.workspace.actions.approvals(month).values()),
    }


# The month's approval of the hours -----------------------------------------------------------


class MonthApproval(BaseModel):
    month: str = Field(pattern=MONTH)
    # A company's group id; None: the plant's own people.
    company: str | None = Field(default=None, max_length=60)


def _approver(rt: Any, user: str, company: str | None) -> None:
    """An administrator approves any month; a company's sponsor at the plant approves its own."""

    access = user_access(rt, user)
    if access is not None and access.is_admin:
        return
    if company:
        group = rt.workspace.groups.get(company)
        if group and group.get("kind") == "company" and group.get("sponsor") == user:
            return
    raise HTTPException(
        status_code=403,
        detail=t("An administrator, or the company's sponsor at the plant, approves its hours."),
    )


@router.post("/hours/approve")
@open_to("viewer")
def approve_hours(payload: MonthApproval, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Closes a month's hours for a company (or the plant): no entry of that month is added or
    removed after, until an administrator reopens it. Kept with who approved and the total."""

    if payload.company:
        group = rt.workspace.groups.get(payload.company)
        if group is None or group.get("kind") != "company":
            raise HTTPException(status_code=404, detail=t("Company not found."))
    _approver(rt, user, payload.company)
    month, first, last = _month_bounds(payload.month)
    entries = _entries_by_company(rt, rt.workspace.actions.hours_between(first, last))
    total = sum(entry["hours"] for entry in entries if entry["company_id"] == payload.company)
    try:
        approval = rt.workspace.actions.approve_month(
            month, payload.company, hours=total, actor=user
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(rt, user, "operations.hours.approved", approval)
    return approval


@router.post("/hours/reopen")
def reopen_hours(payload: MonthApproval, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Opens an approved month again (a correction): the approval is in the audit log."""

    try:
        approval = rt.workspace.actions.reopen_month(payload.month, payload.company)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("These hours are not approved.")) from exc
    _audit(rt, admin, "operations.hours.reopened", approval)
    return {"reopened": approval}


# The requests' service targets -------------------------------------------------------------


@router.get("/targets")
def targets(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """The first answer and resolution targets of requests, by priority, in hours."""

    return {
        "targets": rt.workspace.actions.targets().as_dict(),
        "defaults": Targets.defaults().as_dict(),
    }


@router.put("/targets")
def set_targets(payload: dict[str, Any], admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    before = rt.workspace.actions.targets().as_dict()
    try:
        value = rt.workspace.actions.set_targets(payload.get("targets") or {}, actor=admin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(rt, admin, "operations.targets", {"before": before, "after": value.as_dict()})
    return {"targets": value.as_dict(), "defaults": Targets.defaults().as_dict()}


# Temporary support access ------------------------------------------------------------------


class SupportGrant(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    hours: float = Field(gt=0, le=SUPPORT_MAX_HOURS)
    reason: str = Field(min_length=1, max_length=300)
    action_id: int | None = None


@router.get("/support-access")
def support_access(_reader: OperationsView, rt: Runtime) -> dict[str, Any]:
    """The grants in force and those of the last 30 days."""

    return {"grants": rt.workspace.support_access.recent(), "max_hours": SUPPORT_MAX_HOURS}


@router.post("/support-access/grants", status_code=201)
def grant_support_access(payload: SupportGrant, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Lets a person into Operations for a few hours, for a reason (often a request); they are
    told, and it is in the audit log."""

    users = rt.workspace.users
    username = payload.username.strip().lower()
    if not users.is_active_person(username):
        raise HTTPException(status_code=404, detail=t("Person not found."))
    target = user_access(rt, username)
    if target is not None and target.is_admin:
        raise HTTPException(status_code=409, detail=t("An administrator opens Operations already."))
    if rt.workspace.groups.access_ended(username):
        raise HTTPException(
            status_code=409, detail=t("This person's company access ended: extend it first.")
        )
    if payload.action_id is not None and rt.workspace.actions.get(payload.action_id) is None:
        raise HTTPException(status_code=404, detail=t("Action not found."))
    try:
        grant = rt.workspace.support_access.grant(
            username,
            hours=payload.hours,
            reason=payload.reason,
            actor=admin,
            action_id=payload.action_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(rt, admin, "operations.support_access.granted", grant)
    try:
        rt.notifications.notify(
            "operations",
            "Operations",
            recipients=[f"user:{username}"],
            title=t("You have support access to Operations"),
            text=t(
                "Until {end}: {reason}",
                end=plant_clock(parse_instant(grant["ends_at"])),
                reason=grant["reason"],
            ),
            priority="medium",
            url=f"/actions/{payload.action_id}" if payload.action_id else "/health",
            email=True,
            key=f"support-access:{grant['grant_id']}",
        )
    except (PermissionError, ValueError):
        pass
    return grant


@router.delete("/support-access/grants/{grant_id}")
def end_support_access(grant_id: int, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        grant = rt.workspace.support_access.end(grant_id, actor=admin)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Access not found.")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(rt, admin, "operations.support_access.ended", grant)
    return grant


# Uptime and maintenance windows (plantcraft.watch.uptime) ----------------------------------


@router.get("/uptime")
def uptime(_reader: OperationsView, rt: Runtime) -> dict[str, Any]:
    """Each app's uptime over 24 h, 7 and 30 days (planned maintenance left out), and the
    maintenance windows planned, in force or recent."""

    return rt.watch.uptime()


class MaintenanceWindow(BaseModel):
    # None: now.
    starts_at: str | None = Field(default=None, max_length=40)
    hours: float = Field(gt=0, le=72)
    # Service names; None or empty: every app.
    services: list[str] | None = Field(default=None, max_length=50)
    reason: str = Field(min_length=1, max_length=300)


@router.post("/maintenance/windows", status_code=201)
def plan_maintenance(payload: MaintenanceWindow, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A maintenance window: the watch keeps quiet about the apps it covers while it lasts, and
    the uptime leaves it out. In the audit log."""

    from plantcraft.watch import uptime as maintenance

    now = rt.watch.clock()
    starts = parse_instant(payload.starts_at) if payload.starts_at else now
    if starts is None:
        raise HTTPException(status_code=422, detail=t("Invalid start time."))
    ends = starts + timedelta(hours=payload.hours)
    try:
        reason = maintenance.check_window(starts, ends, payload.reason, now)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    services = [name.strip() for name in payload.services or [] if name.strip()] or None
    window = rt.watch.store.add_window(
        max(starts, now - timedelta(minutes=1)), ends, services, reason, admin
    )
    _audit(rt, admin, "operations.maintenance.planned", window)
    return window


@router.delete("/maintenance/windows/{window_id}")
def end_maintenance(window_id: int, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Ends a window in force now, or cancels a planned one."""

    try:
        window = rt.watch.store.end_window(window_id, admin, rt.watch.clock())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Window not found.")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(rt, admin, "operations.maintenance.ended", window)
    return window
