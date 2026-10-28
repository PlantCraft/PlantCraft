"""Reports: list, open, build, save, copy, delete; read their sections; make, send and keep PDFs.

A report is filed in a folder like a dashboard, and the folder decides who sees and who changes
it. Saved reports read with View's service token (a published report, as dashboards do), drafts
with the editor's own. Every change and every send a person makes is in the audit log.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from plantcraft_sdk.asset_scope import limited
from pydantic import ValidationError

from dashcraft.api.deps import (
    CurrentUser,
    EditorUser,
    EditorView,
    Permissions,
    RuntimeDep,
    dashboard_or_404,
    guarded,
    permissions,
    whole_plant,
)
from dashcraft.api.routers.dashboards import ShareBody, link_days, links_on
from dashcraft.api.views import report_draft, report_reader
from dashcraft.dashboards.model import Conflict, check_window
from dashcraft.delivery.read import read_section
from dashcraft.i18n import t
from dashcraft.reports.model import ReportPayload, Section, SectionPreview
from dashcraft.reports.pdf import Clock

router = APIRouter(prefix="/api", tags=["reports"])
MAX_REPORTS = 500


def _summary(
    rt: RuntimeDep, item: dict[str, Any], perms: Permissions, last: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        **rt.report_service.describe(item),
        "section_count": len(item.get("sections") or []),
        "can_edit": perms.edits(item),
        "last_run": last,
        "public_links": len(rt.dashboards.shares(item["report_id"], "report")),
    }


def report_or_404(rt: RuntimeDep, report_id: str, user: Any) -> dict[str, Any]:
    """A report the person may see (else "not found", so a closed folder says nothing)."""

    found = rt.reports.get(report_id) if len(report_id) <= 40 else None
    if found is not None and not permissions(rt, user).sees(found):
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Report not found."))
    return found


def _editable(rt: RuntimeDep, report_id: str, user: Any) -> dict[str, Any]:
    found = report_or_404(rt, report_id, user)
    if not permissions(rt, user).edits(found):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of its folder change this report.")
        )
    return found


def _folder_open(perms: Permissions, folder_id: str) -> str:
    if folder_id and perms.folder(folder_id) is None:
        raise HTTPException(status_code=422, detail=t("That folder does not exist."))
    if not perms.edits_folder(folder_id):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of that folder add reports to it.")
        )
    return folder_id


def _scheduled(report: dict[str, Any] | None) -> bool:
    return ((report or {}).get("schedule") or {}).get("every", "off") != "off"


def _schedule_allowed(
    user: Any, payload: ReportPayload, found: dict[str, Any] | None = None
) -> None:
    """A scheduled report is made with View's own token: who sees part of the plant neither
    turns a schedule on nor changes a scheduled report."""

    if payload.schedule.on or _scheduled(found):
        whole_plant(user)


def _own_runs(
    rt: RuntimeDep, user: Any, report: dict[str, Any], runs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The PDFs a person may open: all of them; for who sees only part of the plant, the ones
    made at their own request and the ones its editors sent them (a scheduled or "Send now"
    run, to them or a group of theirs). The others were read with View's own token."""

    if not limited(user):
        return runs
    sent_to = set(report.get("recipients") or [])
    addressed = f"user:{user.username}" in sent_to or any(
        f"group:{group}" in sent_to for group in rt.groups_of(user)
    )
    return [
        run
        for run in runs
        if run.get("requested_by") == user.username
        or (addressed and run.get("trigger") in ("schedule", "send"))
    ]


@router.get("/reports")
def list_reports(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    perms = permissions(rt, user)
    last = rt.reports.last_runs()
    return [
        _summary(rt, item, perms, last.get(item["report_id"]))
        for item in rt.reports.list()
        if perms.sees(item)
    ]


@router.post("/reports", status_code=201)
def create_report(payload: ReportPayload, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    perms = permissions(rt, user)
    _folder_open(perms, payload.folder_id)
    _schedule_allowed(user, payload)
    if rt.reports.count() >= MAX_REPORTS:
        raise HTTPException(status_code=409, detail=t("View keeps at most 500 reports."))
    created = rt.report_service.create(payload, user.username)
    rt.audit(user, "report.create", created["report_id"], {"name": created["name"]})
    return _summary(rt, created, perms)


@router.get("/reports/{report_id}")
def get_report(report_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    found = report_or_404(rt, report_id, user)
    return _summary(rt, found, permissions(rt, user), rt.reports.last_runs().get(report_id))


@router.put("/reports/{report_id}", response_model=None)
def update_report(
    report_id: str, payload: ReportPayload, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any] | JSONResponse:
    found = _editable(rt, report_id, user)
    perms = permissions(rt, user)
    _schedule_allowed(user, payload, found)
    if payload.folder_id != found.get("folder_id", ""):
        _folder_open(perms, payload.folder_id)
    try:
        saved = rt.report_service.update(report_id, payload, user.username)
    except Conflict as conflict:
        who = conflict.current.get("updated_by") or t("someone")
        return JSONResponse(
            {
                "detail": t(
                    "{user} saved this report after you opened it. Reload to see their "
                    "changes, or save again to replace them.",
                    user=who,
                ),
                "current": conflict.current,
            },
            status_code=409,
        )
    if saved is None:
        raise HTTPException(status_code=404, detail=t("Report not found."))
    rt.audit(user, "report.update", report_id, {"name": saved["name"]})
    return _summary(rt, saved, perms, rt.reports.last_runs().get(report_id))


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: str, rt: RuntimeDep, user: EditorUser) -> Response:
    found = _editable(rt, report_id, user)
    rt.report_service.delete(report_id)
    # A deleted report's public links stop working.
    rt.dashboards.revoke_all(report_id, user.username, "report")
    rt.audit(user, "report.delete", report_id, {"name": found["name"]})
    return Response(status_code=204)


@router.post("/reports/{report_id}/copy", status_code=201)
def copy_report(report_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """A copy beside the original (in General when the person does not edit that folder),
    with its schedule off, so a copy never sends twice what the original sends."""

    found = report_or_404(rt, report_id, user)
    perms = permissions(rt, user)
    folder_id = found.get("folder_id", "") if perms.edits_folder(found.get("folder_id")) else ""
    try:
        payload = ReportPayload.model_validate(
            {
                **found,
                "name": t("{name} (copy)", name=found["name"])[:120],
                "folder_id": folder_id,
                "schedule": {**(found.get("schedule") or {}), "every": "off"},
                "base_updated_at": None,
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=t("This report cannot be copied.")) from exc
    _folder_open(perms, folder_id)
    created = rt.report_service.create(payload, user.username)
    rt.audit(user, "report.copy", created["report_id"], {"from": report_id})
    return _summary(rt, created, perms)


@router.get("/dashboards/{dashboard_id}/as-report")
def dashboard_as_report(dashboard_id: str, rt: RuntimeDep, user: EditorView) -> dict[str, Any]:
    """What a new report started from this dashboard holds (nothing is saved): New report's
    "Start from a dashboard", the dashboard's pair as a document."""

    return report_draft(rt, dashboard_or_404(rt, dashboard_id, user), user)


# Sections ------------------------------------------------------------------------------


def _period(period: str | None, report: dict[str, Any]) -> str:
    if period in (None, ""):
        return str(report.get("period") or "24h")
    try:
        return check_window(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/reports/{report_id}/sections/{section_id}")
def get_section(
    report_id: str,
    section_id: str,
    rt: RuntimeDep,
    user: CurrentUser,
    period: str | None = Query(default=None, max_length=8),
) -> dict[str, Any]:
    """One section over the report's period ending now (or ``period``), as the PDF reads it."""

    report = report_or_404(rt, report_id, user)
    raw = next(
        (item for item in report.get("sections") or [] if item.get("section_id") == section_id),
        None,
    )
    if raw is None:
        raise HTTPException(status_code=404, detail=t("Section not found."))
    try:
        section = Section.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=t("This section no longer fits the report's rules.")
        ) from exc
    reader, service = report_reader(rt, user)
    window = _period(period, report)
    return guarded(lambda: read_section(reader, section, window), service=service)


@router.post("/report-preview")
def preview_section(body: SectionPreview, rt: RuntimeDep, user: EditorView) -> dict[str, Any]:
    """An unsaved section, read with the editor's own token (PlantCraft's permissions apply)."""

    reader = rt.user_reader(user)
    return guarded(lambda: read_section(reader, body.section, body.period), service=False)


@router.get("/event-kinds")
def event_kinds(rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    """Every event the installed apps declare, for an events section's picker."""

    client = rt.user_client(user)
    catalog = guarded(client.event_catalog, service=False)
    out = []
    for app in catalog or []:
        for spec in app.get("events") or []:
            kind = spec.get("kind") or f"{app.get('app')}.{spec.get('name')}"
            out.append(
                {
                    "kind": kind,
                    "title": spec.get("title") or kind,
                    "app": app.get("name") or app.get("app"),
                    "description": spec.get("description") or "",
                    "severity": spec.get("severity") or "info",
                }
            )
    return out


# Runs and PDFs ------------------------------------------------------------------------


@router.get("/reports/{report_id}/runs")
def list_runs(report_id: str, rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    report = report_or_404(rt, report_id, user)
    return _own_runs(rt, user, report, rt.reports.runs(report_id))


@router.post("/reports/{report_id}/pdf", status_code=201)
def make_pdf(report_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    """The report made now, for the person who asked: kept with the others, sent to nobody."""

    report = report_or_404(rt, report_id, user)
    reader, service = report_reader(rt, user)
    run = guarded(
        lambda: rt.report_service.make(report, reader, trigger="download", by=user.username),
        service=service,
    )
    rt.audit(user, "report.download", report_id, {"run": run["run_id"]})
    return run


@router.post("/reports/{report_id}/send", status_code=201)
def send_report(report_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Make the report now and send it to its recipients, as its schedule would."""

    report = _editable(rt, report_id, user)
    if not report.get("recipients"):
        raise HTTPException(
            status_code=422, detail=t("Add the people or groups the report goes to first.")
        )
    if not rt.has_service_key:
        raise HTTPException(
            status_code=503,
            detail=t(
                "Sending reports needs View's app key: an admin creates one in PlantCraft "
                "and sets PLANTCRAFT_APP_KEY for View."
            ),
        )
    reader, service = report_reader(rt, user)
    run = guarded(
        lambda: rt.report_service.send(report, reader, trigger="send", by=user.username),
        service=service,
    )
    rt.audit(user, "report.send", report_id, {"run": run["run_id"], "status": run["status"]})
    return run


EXPORTS = ("docx", "html", "md")


@router.get("/reports/{report_id}/export/{form}")
def export_report(report_id: str, form: str, rt: RuntimeDep, user: CurrentUser) -> Response:
    """The report read now as Word (.docx), HTML or Markdown, to download: made for whoever may
    open the report, kept nowhere (Download PDF keeps its PDF with the others)."""

    if form not in EXPORTS:
        raise HTTPException(status_code=404, detail=t("View exports Word, HTML and Markdown."))
    report = report_or_404(rt, report_id, user)
    reader, service = report_reader(rt, user)
    content, media_type, name = guarded(
        lambda: rt.report_service.export(report, reader, form), service=service
    )
    rt.audit(user, "report.export", report_id, {"format": form})
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _file_name(report: dict[str, Any], run: dict[str, Any], zone: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", report.get("name") or "report").strip("-").lower()
    day = Clock(zone).text(run.get("period_end"), "%Y-%m-%d")
    return f"{stem[:60] or 'report'}-{day}.pdf"


@router.get("/reports/{report_id}/runs/{run_id}/pdf")
def get_pdf(
    report_id: str,
    run_id: str,
    rt: RuntimeDep,
    user: CurrentUser,
    download: bool = Query(default=False),
) -> Response:
    report = report_or_404(rt, report_id, user)
    run = rt.reports.run(run_id) if len(run_id) <= 40 else None
    if run is None or run["report_id"] != report_id or not _own_runs(rt, user, report, [run]):
        raise HTTPException(status_code=404, detail=t("Run not found."))
    document = rt.reports.pdf(run_id)
    if document is None:
        raise HTTPException(status_code=404, detail=run.get("error") or t("This run made no PDF."))
    name = _file_name(report, run, rt.report_service.zone())
    how = "attachment" if download else "inline"
    return Response(
        document,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{how}; filename="{name}"',
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


# #report:<id> in messages, actions and notes ([[contributes.refs]]) ------------------------


@router.get("/refs/report/{report_id}")
def report_ref(report_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    report = report_or_404(rt, report_id, user)
    return {
        "title": report["name"],
        "status": rt.report_service.cadence(report),
        "url": f"{rt.settings.root_path}/reports/{report_id}",
    }


# Public links: the report as its HTML page, read when opened, without signing in ---------


@router.get("/reports/{report_id}/shares")
def list_shares(report_id: str, rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    if user.demo is not None:  # a demo visit sees the dialog; its links stay the editors'
        return []
    _editable(rt, report_id, user)
    return rt.dashboards.shares(report_id, "report")


@router.post("/reports/{report_id}/shares", status_code=201)
def create_share(report_id: str, body: ShareBody, rt: RuntimeDep, user: EditorUser) -> dict:
    _editable(rt, report_id, user)
    whole_plant(user)
    links_on(rt)
    days = link_days(body, user)
    share, token = rt.dashboards.create_share(
        report_id, user.username, body.label, "report", days=days
    )
    rt.audit(user, "report.share.create", report_id, {"share_id": share["share_id"], "days": days})
    return {**share, "path": f"{rt.settings.root_path}/share/report/{token}"}


@router.delete("/reports/{report_id}/shares/{share_id}", status_code=204)
def revoke_share(report_id: str, share_id: str, rt: RuntimeDep, user: EditorUser) -> Response:
    _editable(rt, report_id, user)
    if not rt.dashboards.revoke_share(report_id, share_id, user.username, "report"):
        raise HTTPException(status_code=404, detail=t("Link not found."))
    rt.audit(user, "report.share.revoke", report_id, {"share_id": share_id})
    return Response(status_code=204)
