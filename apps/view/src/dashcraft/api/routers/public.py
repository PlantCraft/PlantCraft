"""Public links: one dashboard, read-only, without sign-in (a wall screen, a shared link); one
report, as its HTML page (``share/report/<token>``), read when the page is opened; or one
diagram (``share/diagram/<token>``), live or played back on its time bar.

The token in the path is the only key: it is checked against the SHA-256 kept
when the link was made, opens that one dashboard and nothing else, and stops
working when an editor revokes it or deletes the dashboard. Data is read with
View's service token. Turned off with ``DASHCRAFT_PUBLIC_LINKS=false``.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from dashcraft.api.deps import RuntimeDep, guarded
from dashcraft.api.routers.diagrams import diagram_end, diagram_window
from dashcraft.api.views import (
    card_data,
    context_options,
    dashboard_variable_options,
    public_dashboard,
    public_diagram,
    raw_values,
    report_reader,
)
from dashcraft.diagrams.model import on_page
from dashcraft.diagrams.read import read_diagram
from dashcraft.i18n import t
from dashcraft.reports import html as report_html

router = APIRouter(prefix="/api/public", tags=["public links"])
pages = APIRouter(tags=["public links"])
# The report's page holds its own styles, script and data, and reaches for nothing else. Its one
# script runs by its hash, nothing else inline does; the suite's proxy leaves this page its own
# policy (deploy/proxy/Caddyfile), since the suite's "script-src 'self'" would stop the charts.
SCRIPT_HASH = base64.b64encode(hashlib.sha256(report_html.SCRIPT.encode()).digest()).decode()
REPORT_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        f"default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{SCRIPT_HASH}'; "
        "img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    ),
}


def _shared_diagram(rt: RuntimeDep, token: str) -> dict[str, Any]:
    diagram_id = rt.dashboards.resolve_share(token, "diagram") if rt.settings.public_links else None
    diagram = rt.diagrams.get(diagram_id) if diagram_id else None
    if diagram is None:
        raise HTTPException(
            status_code=404,
            detail=t("This link does not open a process display (revoked or wrong)."),
        )
    return diagram


# Diagrams first: ``diagram/<token>`` must not be read as a dashboard token "diagram".
@router.get("/diagram/{token}")
def shared_diagram(token: str, rt: RuntimeDep) -> dict[str, Any]:
    return public_diagram(_shared_diagram(rt, token))


@router.get("/diagram/{token}/data")
def shared_diagram_data(
    token: str,
    rt: RuntimeDep,
    window: str | None = Query(default=None, max_length=8),
    end: str | None = Query(default=None, max_length=40),
    page: str | None = Query(default=None, max_length=40),
) -> dict[str, Any]:
    """Every binding's value now (or at ``end``) and the window's series, as the diagram's own
    page reads them, with View's service token."""

    diagram = on_page(_shared_diagram(rt, token), page)
    reader, service = report_reader(rt, None)
    picked, until = diagram_window(window), diagram_end(end)
    return guarded(lambda: read_diagram(reader, diagram, picked, until), service=service)


def _shared(rt: RuntimeDep, token: str) -> dict[str, Any]:
    dashboard_id = rt.dashboards.resolve_share(token) if rt.settings.public_links else None
    dashboard = rt.dashboards.get(dashboard_id) if dashboard_id else None
    if dashboard is None:
        raise HTTPException(
            status_code=404, detail=t("This link does not open a dashboard (revoked or wrong).")
        )
    return dashboard


@router.get("/{token}")
def shared_dashboard(token: str, rt: RuntimeDep) -> dict[str, Any]:
    return public_dashboard(_shared(rt, token))


@router.get("/{token}/cards/{card_id}")
def shared_card(
    token: str,
    card_id: str,
    request: Request,
    rt: RuntimeDep,
    context: str | None = Query(default=None, max_length=300),
    window: str | None = Query(default=None, max_length=8),
) -> dict[str, Any]:
    return card_data(
        rt,
        _shared(rt, token),
        card_id,
        user=None,
        context=context,
        window=window,
        raw=raw_values(request.query_params),
    )


@router.get("/{token}/variables/{name}")
def shared_variable_options(
    token: str,
    name: str,
    rt: RuntimeDep,
    parent: list[str] = Query(default_factory=list, max_length=25),
) -> list[dict[str, Any]]:
    return dashboard_variable_options(rt, _shared(rt, token), name, parent, None)


@router.get("/{token}/context")
def shared_context(token: str, rt: RuntimeDep) -> list[dict]:
    return context_options(rt, _shared(rt, token), None)


@pages.get("/share/report/{token}", response_class=HTMLResponse)
def shared_report(token: str, rt: RuntimeDep) -> HTMLResponse:
    report_id = rt.dashboards.resolve_share(token, "report") if rt.settings.public_links else None
    report = rt.reports.get(report_id) if report_id else None
    if report is None or not rt.has_service_key:
        return HTMLResponse(
            f"<!doctype html><title>{t('Link not found')}</title><p>"
            f"{t('This link does not open a report (revoked or wrong).')}</p>",
            status_code=404,
            headers=REPORT_PAGE_HEADERS,
        )
    reader, _service = report_reader(rt, None)
    page = rt.report_service.page(report, reader)
    return HTMLResponse(page, headers=REPORT_PAGE_HEADERS)
