"""Request dependencies shared by the routers."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException, Request, status

from plantcraft.actions import Visibility
from plantcraft.api.runtime import ApiRuntime
from plantcraft.auth.access import Access
from plantcraft.auth.public_demo import public_demo
from plantcraft.desk import VISIT_OWNER
from plantcraft.i18n import t
from plantcraft.platform.asset_scope import AssetScope, check_roots


def get_runtime(request: Request) -> ApiRuntime:
    return request.app.state.runtime


Runtime = Annotated[ApiRuntime, Depends(get_runtime)]


def password_fingerprint(rt: ApiRuntime, username: str) -> str:
    """Stored in the session at sign-in; a new password invalidates old sessions."""

    if username == rt.auth.username:
        return hashlib.sha256(f"admin:{rt.auth.password}".encode()).hexdigest()[:16]
    return rt.workspace.users.password_fingerprint(username)


def session_user(request: Request, rt: ApiRuntime) -> str | None:
    """The signed-in username, or None when the session is not valid."""

    username = request.session.get("cpm_username")
    if not rt.auth.enabled:
        # Local and demo use: whoever the session picked, else the default user.
        if username and rt.workspace.users.get_user(username):
            return str(username)
        return rt.default_user()
    if not username:
        return None
    sid = request.session.get("cpm_sid")
    if not isinstance(sid, str) or not sid or rt.workspace.ended_sessions.ended(sid):
        # Signed out (plantcraft.auth.sessions), or a cookie from before session ids.
        return None
    demo = public_demo()
    if demo is not None and username == demo.username:
        # A visit of the public demo lasts while its place does (plantcraft.auth.demo_visits);
        # from outside, the visitor account is only ever a visit.
        visit = request.session.get("demo_visit")
        if visit:
            return str(username) if rt.workspace.demo_visits.get(str(visit)) else None
        if from_outside(request):
            return None
    if request.session.get("cpm_fp") != password_fingerprint(rt, str(username)):
        return None
    if username == rt.auth.username:
        return str(username)
    if rt.workspace.groups.access_ended(str(username)):
        # Their company's access ended (plantcraft.groups, ``access_until``).
        return None
    source, _external_id = rt.workspace.users.identity(str(username))
    if source == "local":
        if not rt.directory.settings().local_passwords:
            # Corporate sign-in only: passwords kept here end, but the installation's admin's.
            return None
        return str(username) if rt.workspace.users.has_password(username) else None
    return str(username) if directory_session_valid(request, rt, str(username), source) else None


# Set by the suite's proxy on every request it forwards from outside (deploy/proxy/Caddyfile).
EDGE_HEADER = "x-plantcraft-edge"


def from_outside(request: Request) -> bool:
    """The request came through the suite's proxy (a browser), not from inside the network."""

    return request.headers.get(EDGE_HEADER) == "1"


def demo_visit(request: Request, rt: ApiRuntime):
    """The public demo visit this session is, or None."""

    demo = public_demo()
    visit = request.session.get("demo_visit")
    if demo is None or not visit or request.session.get("cpm_username") != demo.username:
        return None
    return rt.workspace.demo_visits.get(str(visit))


def marks_owner(request: Request, rt: ApiRuntime, username: str) -> str:
    """Whose marks (read, done, favorite, unread again) a request reads and writes: the person's,
    or on a public demo the visit's own (``demo#visit:<id>``), so a visitor's marks never reach
    the next visitor, who starts from the demo as seeded."""

    visit = demo_visit(request, rt)
    return f"{username}{VISIT_OWNER}{visit.visit}" if visit is not None else username


def claims_marks_owner(username: str, claims: dict[str, Any]) -> str:
    """``marks_owner`` from a token's claims (API v1: a demo visit's token names its visit)."""

    demo = claims.get("demo")
    if isinstance(demo, dict) and demo.get("visit") and public_demo() is not None:
        return f"{username}{VISIT_OWNER}{demo['visit']}"
    return username


def directory_session_valid(request: Request, rt: ApiRuntime, username: str, source: str) -> bool:
    """A person from the company directory: active here, their way in still on, and signed in
    within the hours set in Settings (so a person turned off in the directory loses access soon)."""

    settings = rt.directory.settings()
    if not settings.method_enabled(source) or not rt.workspace.users.is_active_person(username):
        return False
    try:
        signed_in = float(request.session.get("cpm_auth_at") or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= time.time() - signed_in <= settings.session_hours * 3600


def user_access(rt: ApiRuntime, username: str | None) -> Access | None:
    """The person's access profile; None for nobody.

    People with no level set keep the behaviour they had before levels existed:
    with sign-in off everyone is the local operator (admin); signed in, a person
    is an editor unless marked administrator. The environment's account is admin.
    """

    if not username:
        return None
    if rt.auth.enabled and username == rt.auth.username:
        return Access("admin")
    access = rt.workspace.users.access(username, default="editor" if rt.auth.enabled else "admin")
    if access is None and not rt.auth.enabled:
        # Sign-in off with no people at all: the local operator.
        return Access("admin")
    return access


def action_visibility(rt: ApiRuntime, username: str) -> Visibility:
    """The actions ``username`` sees (docs/collaboration.md, "Who sees an action"): an
    administrator every one, and so does the public demo's read-only visitor (the demo shows
    the team's follow-up); anyone else theirs, their groups' and those below a group they
    lead."""

    scope = rt.workspace.groups.scope(username)
    access = user_access(rt, username)
    demo = public_demo()
    assets = rt.asset_scope(username)
    return Visibility(
        username,
        everything=bool(access and access.is_admin) or bool(demo and demo.username == username),
        people=frozenset(scope["people"]),
        groups=frozenset(scope["groups"]),
        requests=bool(access and access.can_operate),
        # Actions only about assets out of their asset scope (docs/asset-scope.md).
        out_of_scope=frozenset()
        if assets.everything
        else frozenset(
            action_id
            for action_id, refs in rt.workspace.actions.plant_refs().items()
            if not assets.refs(refs)
        ),
    )


def asset_roots(rt: ApiRuntime, roots: list[str] | None) -> list[str] | None:
    """An asset scope as given, checked against the tree (422 for an unknown asset)."""

    try:
        return check_roots(rt.workspace, roots)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"{t('Asset not found.')} ({exc.args[0]})"
        ) from exc


def is_admin(rt: ApiRuntime, username: str | None) -> bool:
    access = user_access(rt, username)
    return bool(access and access.is_admin)


def request_access(request: Request, rt: ApiRuntime) -> tuple[str | None, Access | None]:
    """The signed-in person and their access, computed once per request."""

    cached = getattr(request.state, "access", None)
    if cached is None:
        username = session_user(request, rt)
        cached = request.state.access = (username, user_access(rt, username))
    return cached


_Endpoint = TypeVar("_Endpoint", bound=Callable[..., Any])


def open_to(level: str) -> Callable[[_Endpoint], _Endpoint]:
    """The lowest access level a route accepts, overriding the router's rule.

    ``@open_to("dashboards")`` lets dashboards-only people in (dashboard views and
    their queries); ``@open_to("viewer")`` marks a POST that only reads (a
    preview) or a conversation write; ``@open_to("editor")`` a GET that is
    engineering-only. Place it under the ``@router`` decorator.
    """

    def mark(endpoint: _Endpoint) -> _Endpoint:
        endpoint.min_access = level  # type: ignore[attr-defined]
        return endpoint

    return mark


_READS = {"GET", "HEAD", "OPTIONS"}
# A public demo's visitor may still sign out and mark what they read: state of their own session,
# never content another visitor reads.
_VISITOR_WRITES = re.compile(
    r"^/api/(logout|demo/(enter|heartbeat)|messages/conversations/\d+/read|notifications/marks|me/marks|desk/triage)$"
)
_DENIED = {
    "dashboards": "Your access is limited to dashboards.",
    "viewer": "Your access is read-only.",
    "editor": "Only admins can make this change.",
}


def access_guard(
    application: str | None = None, write_level: str = "editor"
) -> Callable[..., None]:
    """Router-wide check of the access profile, added where the routers are mounted.

    Reads need ``viewer``, writes ``write_level`` (``editor`` unless the router
    says otherwise, as conversations do), unless the route is marked with
    ``open_to``. The router's ``application`` and any ``application_id`` in the
    path or query must be one the person has. Requests with no session pass
    through: the route's own ``CurrentUser`` answers 401.
    """

    def guard(request: Request, rt: Runtime) -> None:
        username, access = request_access(request, rt)
        if username is None or access is None:
            return
        # A public demo's visitors read only: not even a conversation another visitor would see.
        if (
            request.method not in _READS
            and not access.at_least("editor")
            and not _VISITOR_WRITES.match(request.url.path)
            and public_demo()
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=t("This is a public demo: you can try everything, but nothing is saved."),
            )
        endpoint = request.scope.get("endpoint")
        needed = getattr(endpoint, "min_access", None) or (
            "viewer" if request.method in _READS else write_level
        )
        if not access.at_least(needed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=t(_DENIED[access.level])
            )
        wanted = {
            application,
            request.path_params.get("application_id"),
            request.query_params.get("application_id"),
        }
        for app_id in wanted - {None}:
            if not access.allows(str(app_id)):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=t("You do not have access to this application."),
                )
        # An asset out of the person's asset scope is not there for them (docs/asset-scope.md).
        asset_id = request.path_params.get("asset_id")
        if asset_id is not None and not current_scope(request, rt).asset(str(asset_id)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("Asset not found."))

    return guard


def current_access(request: Request, rt: Runtime) -> Access:
    _username, access = request_access(request, rt)
    return access or Access("viewer", ())


UserAccess = Annotated[Access, Depends(current_access)]


def authenticated(request: Request, rt: Runtime) -> str:
    username = session_user(request, rt)
    if not username:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("Session expired. Sign in again."),
        )
    return username


CurrentUser = Annotated[str, Depends(authenticated)]


def administrator(username: CurrentUser, rt: Runtime) -> str:
    if not is_admin(rt, username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=t("Only admins can make this change."),
        )
    return username


AdminUser = Annotated[str, Depends(administrator)]


def administration_reader(username: CurrentUser, rt: Runtime) -> str:
    """An administrator, or the public demo's visitor: a visitor sees the administration pages
    (people and groups, apps, backups) to know the platform, read-only; every
    change there still needs an administrator."""

    demo = public_demo()
    if demo is not None and username == demo.username:
        return username
    return administrator(username, rt)


AdminView = Annotated[str, Depends(administration_reader)]


def operations_reader(request: Request, username: CurrentUser, rt: Runtime) -> str:
    """Who may open Operations (status, load, logs): an administrator, a person with the
    Operations role (``Access.can_operate``), or the public demo's visitor (read-only)."""

    demo = public_demo()
    if demo is not None and username == demo.username:
        return username
    _username, access = request_access(request, rt)
    if access is None or not access.can_operate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=t("Only admins and people with the Operations role can open this."),
        )
    return username


OperationsView = Annotated[str, Depends(operations_reader)]


def current_scope(request: Request, rt: Runtime) -> AssetScope:
    """The assets the signed-in person sees (docs/asset-scope.md), computed once per request."""

    cached = getattr(request.state, "asset_scope", None)
    if cached is None:
        username, _access = request_access(request, rt)
        cached = request.state.asset_scope = rt.asset_scope(username)
    return cached


Scope = Annotated[AssetScope, Depends(current_scope)]
