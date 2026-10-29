"""HTTP routes: visits of a public demo ("Enter the demo", the line, the visit's clock), and the
pages the demo's guides by role open.

The visits are only on a public demo (``PLANTCRAFT_PUBLIC_DEMO``); elsewhere those routes are a
404. The places, the line and when a visitor gives their place up:
``processcraft.auth.demo_visits``. The guides work on any installation the demo story was seeded
on (``processcraft demo seed``), for whoever is signed in.
"""

from __future__ import annotations

import ipaddress
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from processcraft.api.deps import CurrentUser, Runtime, demo_visit
from processcraft.api.identity import refresh_browser_token
from processcraft.api.routers.session import _session_payload, audit_sign_in, open_session
from processcraft.auth.demo_visits import Visit
from processcraft.auth.public_demo import PublicDemo, public_demo
from processcraft.i18n import t

router = APIRouter()


class EnterPayload(BaseModel):
    # The ticket of the browser's last answer while it waited in line.
    ticket: str | None = Field(default=None, max_length=64)
    # The guide the visitor picked ("operator", "engineer"...), kept in the audit log of the
    # visit: which people the demo interests. Never shown to another visitor.
    guide: str | None = Field(default=None, max_length=32, pattern=r"^[a-z][a-z-]*$")


class HeartbeatPayload(BaseModel):
    # The page is open, in front, and the visitor used it since the last one.
    active: bool = False
    # The paths the visitor had in front since the last one (the demo's stats).
    pages: list[str] = Field(default_factory=list, max_length=20)


def _demo() -> PublicDemo:
    demo = public_demo()
    if demo is None:
        raise HTTPException(status_code=404, detail=t("Not found."))
    return demo


def _place_of(host: str) -> str:
    """Where a visitor comes from, for the places per address: an IPv6 address by its /64, the
    block one home or office is given (each device there has its own address)."""

    try:
        found = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(found, ipaddress.IPv6Address):
        if found.ipv4_mapped:
            return str(found.ipv4_mapped)
        return str(ipaddress.ip_network(f"{found}/64", strict=False))
    return str(found)


@router.post("/api/demo/enter")
def enter(
    payload: EnterPayload, request: Request, response: Response, rt: Runtime
) -> dict[str, Any]:
    """A visit of the demo, or this browser's place in line (ask again with its ticket)."""

    demo = _demo()
    if not rt.workspace.users.is_active_person(demo.username):
        raise HTTPException(
            status_code=503, detail=t("The demo is being prepared. Try again in a few minutes.")
        )
    current = demo_visit(request, rt)
    if current is None:
        found = rt.workspace.demo_visits.enter(
            seats=demo.seats,
            minutes=demo.minutes,
            idle_minutes=demo.idle_minutes,
            address=_place_of(request.client.host if request.client else "-"),
            ticket=payload.ticket,
        )
        if not isinstance(found, Visit):
            return {
                "entered": False,
                "ticket": found.ticket or None,
                "position": found.position,
                "wait_seconds": found.wait_seconds,
                "seats": demo.seats,
            }
        open_session(request, rt, demo.username)
        request.session["demo_visit"] = found.visit
        detail = {"guide": payload.guide} if payload.guide else {}
        audit_sign_in(rt, request, demo.username, "session.sign_in", method="demo", **detail)
    refresh_browser_token(request, response, rt)
    return {"entered": True, **_session_payload(demo.username, rt, request)}


@router.post("/api/demo/heartbeat")
def heartbeat(payload: HeartbeatPayload, request: Request, rt: Runtime) -> dict[str, Any]:
    """A sign of life from a visit's frame: how long the visit has left (401 once it ended)."""

    demo = _demo()
    visit = request.session.get("demo_visit")
    found = (
        rt.workspace.demo_visits.seen(str(visit), active=payload.active, minutes=demo.minutes)
        if visit
        else None
    )
    if found is None:
        raise HTTPException(status_code=401, detail=t("Your demo visit ended."))
    if payload.pages:
        rt.workspace.demo_visits.opened(str(visit), payload.pages)
    return {"seconds_left": found.seconds_left(), "minutes": demo.minutes}


@router.get("/api/demo/stats")
def stats(
    request: Request, rt: Runtime, days: int = Query(default=31, ge=1, le=400)
) -> dict[str, Any]:
    """How many people visit the demo and for how long, for the site's private stats page: the
    visits started in the last ``days`` days and the places taken now. No addresses. Only with
    ``PLANTCRAFT_PUBLIC_DEMO_STATS_KEY`` as the bearer token; otherwise a 404."""

    demo = _demo()
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not demo.stats_key or not secrets.compare_digest(given.encode(), demo.stats_key.encode()):
        raise HTTPException(status_code=404, detail=t("Not found."))
    now = time.time()
    return {
        "now": {**rt.workspace.demo_visits.counts(now), "seats": demo.seats},
        "visits": rt.workspace.demo_visits.history(now - days * 86400, now),
        "pages": rt.workspace.demo_visits.pages(now - days * 86400),
        "journeys": rt.workspace.demo_visits.journeys(now - days * 86400, now=now),
    }


@router.get("/api/demo/guides")
def guides(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """The pages the demo story's names open on this installation (empty before a demo seed)."""

    return {"links": rt.workspace.demo_visits.guide_links()}
