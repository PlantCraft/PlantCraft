"""HTTP routes: user administration (people, their access level, apps and role in each app)
and profiles.

Everyone signed in can list the people (``GET /api/users``) and open a person's
profile (``GET /api/people/<username>``); each person edits their own profile
(``/api/me/profile``); managing accounts is for administrators. Rows of another ``kind`` than ``person`` (the specialist
bots of the former monolith) are left out everywhere.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plantcraft.api.deps import (
    AdminUser,
    AdminView,
    CurrentUser,
    Runtime,
    action_visibility,
    asset_roots,
    is_admin,
    open_to,
    user_access,
)
from plantcraft.auth.access import LEVEL_LABELS, OPERATIONS_APP, level_label
from plantcraft.auth.suite import FORMER_IDS, app_access
from plantcraft.i18n import t
from plantcraft.platform.asset_scope import MAX_SCOPE_ROOTS, scope_roots

# What /api/users shows to someone who is not an administrator.
DIRECTORY_FIELDS = ("username", "display_name", "role", "active", "kind")

router = APIRouter()

Level = Literal["admin", "editor", "viewer", "dashboards"]
AppRole = Literal["viewer", "editor"]
AppRoles = Annotated[dict[str, AppRole], Field(max_length=40)]
AssetId = Annotated[str, Field(min_length=1, max_length=200)]


class Profile(BaseModel):
    job_title: str = Field(default="", max_length=120)
    affiliation: Literal["", "internal", "external"] = ""
    organization: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=40)
    unit: str = Field(default="", max_length=120)


class MyProfile(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=120)
    profile: Profile = Field(default_factory=Profile)


class UserCreatePayload(BaseModel):
    username: str = Field(min_length=2, max_length=60)
    display_name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=120)
    password: str | None = Field(default=None, max_length=200)
    access_level: Level = "viewer"
    applications: list[str] | None = Field(default=None, max_length=40)
    app_roles: AppRoles = Field(default_factory=dict)
    profile: Profile | None = None
    groups: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list, max_length=200)
    # The roots of the asset tree they see (docs/asset-scope.md); None: the whole plant.
    asset_scope: list[AssetId] | None = Field(default=None, max_length=MAX_SCOPE_ROOTS)


class UserUpdatePayload(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=120)
    access_level: Level
    applications: list[str] | None = Field(default=None, max_length=40)
    # Left out: kept as they are.
    app_roles: AppRoles | None = None
    profile: Profile | None = None
    groups: list[Annotated[str, Field(max_length=60)]] | None = Field(default=None, max_length=200)
    active: bool = True
    # Left out: kept as it is; null: the whole plant.
    asset_scope: list[AssetId] | None = Field(default=None, max_length=MAX_SCOPE_ROOTS)


class PasswordPayload(BaseModel):
    password: str = Field(min_length=8, max_length=200)


def _account(rt: Any, user: dict[str, Any]) -> dict[str, Any]:
    access = user_access(rt, user["username"]) if user.get("active") else None
    level = (
        access.level
        if access
        else (user.get("access_level") or ("admin" if user.get("is_admin") else "editor"))
    )
    return {
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "active": bool(user["active"]),
        "access_level": level,
        "access_label": level_label(level),
        "applications": user.get("applications"),
        "app_roles": user.get("app_roles") or {},
        "profile": user.get("profile") or {},
        "has_password": rt.workspace.users.has_password(user["username"]),
        # local, ldap or oidc: a person from the company directory signs in there.
        "auth_source": user.get("auth_source") or "local",
        "environment_admin": rt.auth.enabled and user["username"] == rt.auth.username,
        # A person may be in several groups.
        "groups": [item["group_id"] for item in rt.workspace.groups.of(user["username"])],
        "asset_scope": user.get("asset_scope"),
        # What they see in the end: their roots and their limited groups'; None: the whole plant.
        "asset_roots": None
        if access is None or access.is_admin
        else scope_roots(rt.workspace, user["username"]),
    }


def _person(rt: Any, username: str) -> dict[str, Any]:
    user = rt.workspace.users.get_user(username)
    if user is None or user.get("kind", "person") != "person":
        raise HTTPException(status_code=404, detail=t("User not found."))
    return user


def _choices(rt: Any) -> list[dict[str, str]]:
    """The apps of the suite: ``PLANTCRAFT_APPS`` and the ones installed from the Apps page."""

    return [{"application_id": app.id, "name": app.name} for app in rt.suite_apps()]


def _applications(rt: Any, applications: list[str] | None) -> list[str] | None:
    if applications is None:
        return None
    known = {app["application_id"] for app in _choices(rt)}
    # Access granted before the apps left PlantCraft may name the module they grew from.
    known |= {former for app_id in known for former in FORMER_IDS.get(app_id, ())}
    unknown = sorted(set(applications) - known)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=t("Unknown application: {applications}.", applications=", ".join(unknown)),
        )
    return sorted(set(applications))


def _app_roles(rt: Any, roles: dict[str, str]) -> dict[str, str]:
    # Operations is built in (plantcraft.auth.access.OPERATIONS_APP), not a suite app.
    _applications(rt, [app_id for app_id in roles if app_id != OPERATIONS_APP])
    return dict(roles)


@router.get("/api/users")
@open_to("dashboards")
def people(user: CurrentUser, rt: Runtime) -> list[dict[str, Any]]:
    """The people of the installation, for anyone signed in: names and roles only.

    An administrator gets each person's whole record (access, sign-in source, profile); anyone
    else only what picking a person needs, so nobody copies everyone's e-mail, phone and access
    in one call (a person's own page, ``/api/people/<name>``, still shows what they shared).
    """

    people = rt.workspace.users.list_users(kind="person")
    if is_admin(rt, user):
        return people
    return [{key: person.get(key) for key in DIRECTORY_FIELDS} for person in people]


@router.get("/api/users/accounts")
def accounts(_admin: AdminView, rt: Runtime) -> dict[str, Any]:
    """Every person, active or not, with their access; and the levels and applications to choose from."""

    people = rt.workspace.users.list_users(active_only=False, kind="person")
    return {
        "users": [_account(rt, user) for user in people],
        "levels": [{"id": key, "label": level_label(key)} for key in LEVEL_LABELS],
        "applications": _choices(rt),
        "groups": [
            {"group_id": item["group_id"], "name": item["name"], "kind_label": item["kind_label"]}
            for item in rt.workspace.groups.list()
        ],
        "sign_in": rt.auth.enabled,
    }


@router.post("/api/users", status_code=201)
def create_user(payload: UserCreatePayload, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    users = rt.workspace.users
    username = payload.username.strip().lower()
    if users.get_user(username) is not None:
        raise HTTPException(status_code=409, detail=t("A user with this name already exists."))
    applications = _applications(rt, payload.applications)
    scope = asset_roots(rt, payload.asset_scope)
    known = {item["group_id"] for item in rt.workspace.groups.list()}
    unknown = [group for group in payload.groups if group not in known]
    if unknown:
        raise HTTPException(
            status_code=422, detail=t("Group not found: {group}.", group=unknown[0])
        )
    if payload.password and len(payload.password) < 8:
        # Checked before the account exists, so a weak password creates nothing.
        raise HTTPException(
            status_code=422, detail=t("The password must have at least 8 characters.")
        )
    try:
        app_roles = _app_roles(rt, payload.app_roles)
        user = users.upsert_user(username, payload.display_name, payload.role)
        users.set_access(user["username"], payload.access_level, applications)
        users.set_app_roles(user["username"], app_roles)
        if payload.profile is not None:
            users.set_profile(user["username"], payload.profile.model_dump())
        if payload.password:
            users.set_password(user["username"], payload.password)
        if payload.groups:
            rt.workspace.groups.set_groups_of(user["username"], payload.groups)
        users.set_asset_scope(user["username"], scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account(rt, _person(rt, user["username"]))


@router.put("/api/users/{username}")
def update_user(
    username: str, payload: UserUpdatePayload, admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    users = rt.workspace.users
    _person(rt, username)
    if rt.auth.enabled and username == rt.auth.username:
        raise HTTPException(
            status_code=422, detail=t("The environment administrator is set by the installation.")
        )
    if username == admin and (payload.access_level != "admin" or not payload.active):
        raise HTTPException(status_code=422, detail=t("You cannot remove your own admin access."))
    applications = _applications(rt, payload.applications)
    app_roles = None if payload.app_roles is None else _app_roles(rt, payload.app_roles)
    scope_given = "asset_scope" in payload.model_fields_set
    scope = asset_roots(rt, payload.asset_scope) if scope_given else None
    users.update_profile(username, payload.display_name, payload.role)
    try:
        if payload.profile is not None:
            users.set_profile(username, payload.profile.model_dump())
        users.set_access(username, payload.access_level, applications)
        if app_roles is not None:
            users.set_app_roles(username, app_roles)
        if payload.groups is not None:
            rt.workspace.groups.set_groups_of(username, payload.groups)
            rt.workspace.messages.sync(username)
        if scope_given:
            users.set_asset_scope(username, scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.active:
        users.activate(username)
    else:
        users.deactivate(username)
    return _account(rt, _person(rt, username))


@router.post("/api/users/{username}/password")
def reset_password(
    username: str, payload: PasswordPayload, _admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    """A new password; the person's open sessions end."""

    _person(rt, username)
    if rt.auth.enabled and username == rt.auth.username:
        raise HTTPException(
            status_code=422,
            detail=t("The environment administrator's password is kept in the secret file."),
        )
    try:
        rt.workspace.users.set_password(username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account(rt, _person(rt, username))


def _card(rt: Any, user: dict[str, Any], *, viewer: str) -> dict[str, Any]:
    """A person's profile page: who they are, how to reach them and what they own."""

    actions = rt.workspace.actions.list(
        statuses=["open", "in_progress", "blocked"],
        owner=user["username"],
        limit=50,
        visible=action_visibility(rt, viewer),
    )
    card = {
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "active": bool(user["active"]),
        "profile": user.get("profile") or {},
        "actions": [
            {
                "action_id": item["action_id"],
                "title": item["title"],
                "status": item["status"],
                "status_label": item["status_label"],
                "due_at": item["due_at"],
                "overdue": item["overdue"],
            }
            for item in actions
        ],
        "is_me": viewer == user["username"],
        "groups": rt.workspace.groups.of(user["username"]),
    }
    # Access is the person's own business and the administrators'.
    access = user_access(rt, viewer)
    if card["is_me"] or (access is not None and access.is_admin):
        card["access"] = _account(rt, user)
        roles = app_access(user_access(rt, user["username"]), rt.suite_apps())
        card["apps"] = [
            {"application_id": app.id, "name": app.name, "role": roles[app.id]}
            for app in rt.suite_apps()
            if app.id in roles
        ]
    return card


@router.get("/api/people/{username}")
@open_to("dashboards")
def person(username: str, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A person's profile, for anyone signed in; their access only for themselves and admins."""

    return _card(rt, _person(rt, username), viewer=user)


@router.get("/api/me/profile")
@open_to("dashboards")
def my_profile(user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    found = rt.workspace.users.get_user(user)
    if found is None:
        raise HTTPException(status_code=404, detail=t("User not found."))
    return _card(rt, found, viewer=user)


@router.put("/api/me/profile")
@open_to("dashboards")
def save_my_profile(payload: MyProfile, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Each person keeps their own name, sector and profile; access stays with the admins."""

    users = rt.workspace.users
    found = users.get_user(user)
    if found is None or found.get("kind", "person") != "person":
        raise HTTPException(status_code=404, detail=t("User not found."))
    try:
        users.update_profile(user, payload.display_name, payload.role)
        users.set_profile(user, payload.profile.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _card(rt, _person(rt, user), viewer=user)
