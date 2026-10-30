"""HTTP routes: Settings › Corporate sign-in (administrators): the LDAP or Active Directory server,
the OIDC provider, the group rules, and a test of each (docs/corporate-login.md)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plantcraft.api.deps import AdminUser, Runtime
from plantcraft.directory import check_settings, map_access
from plantcraft.directory.ldap import LdapDirectory
from plantcraft.i18n import t

router = APIRouter()


class DirectoryPayload(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    # Left empty: the stored secret stays.
    ldap_bind_password: str = Field(default="", max_length=1000)
    clear_ldap_bind_password: bool = False
    oidc_client_secret: str = Field(default="", max_length=2000)
    clear_oidc_client_secret: bool = False


class LdapTest(DirectoryPayload):
    username: str = Field(default="", max_length=256)
    password: str = Field(default="", max_length=1000)


class MappingPreview(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    groups: list[str] = Field(default_factory=list, max_length=1000)


def _public(rt: Any) -> dict[str, Any]:
    return {
        **rt.directory.settings().public(rt.directory.secrets.present()),
        "sign_in_enabled": rt.auth.enabled,
        "admin_account": rt.auth.username or None,
        "apps": [{"id": app.id, "name": app.name} for app in rt.suite_apps()],
        "groups": [
            {"group_id": group["group_id"], "name": group["name"]}
            for group in rt.workspace.groups.list()
        ],
    }


def _checked(rt: Any, raw: dict[str, Any], *, strict: bool = True):
    try:
        return check_settings(
            raw,
            app_ids={app.id for app in rt.suite_apps()} if strict else None,
            group_ids={group["group_id"] for group in rt.workspace.groups.list()}
            if strict
            else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _ldap_target(settings: Any) -> tuple[str, str]:
    return (" ".join(settings.ldap.url.split()), settings.ldap.bind_dn.strip())


def _oidc_target(settings: Any) -> tuple[str, str]:
    return (settings.oidc.issuer.strip().rstrip("/"), settings.oidc.client_id.strip())


def _secret_follows(rt: Any, name: str, saved: Any, wanted: Any, typed: str, cleared: bool) -> None:
    """A saved secret only goes to the server it was typed for. When the address (or the account)
    changes, the admin types it again: otherwise anyone who could change the address could send
    the company's service password to a server of their own (security audit 2026-10-22)."""

    if typed or cleared or saved == wanted or not wanted[0] or not rt.directory.secrets.get(name):
        return
    raise HTTPException(
        status_code=422,
        detail=t(
            "The server changed: type the password again, so the saved one is never sent to "
            "another server."
        ),
    )


@router.get("/api/directory")
def directory(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The corporate sign-in settings (never the secrets: only whether they are saved)."""

    return _public(rt)


@router.put("/api/directory")
def save_directory(payload: DirectoryPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    settings = _checked(rt, payload.settings)
    saved = rt.directory.settings()
    _secret_follows(
        rt,
        "ldap_bind_password",
        _ldap_target(saved),
        _ldap_target(settings),
        payload.ldap_bind_password,
        payload.clear_ldap_bind_password,
    )
    _secret_follows(
        rt,
        "oidc_client_secret",
        _oidc_target(saved),
        _oidc_target(settings),
        payload.oidc_client_secret,
        payload.clear_oidc_client_secret,
    )
    secrets = rt.directory.secrets
    if payload.clear_ldap_bind_password:
        secrets.set("ldap_bind_password", None)
    elif payload.ldap_bind_password:
        secrets.set("ldap_bind_password", payload.ldap_bind_password)
    if payload.clear_oidc_client_secret:
        secrets.set("oidc_client_secret", None)
    elif payload.oidc_client_secret:
        secrets.set("oidc_client_secret", payload.oidc_client_secret)
    rt.directory.store.save(settings, admin)
    rt.workspace.audit.record(
        admin,
        "directory.settings",
        "directory",
        {
            "ldap": settings.ldap.enabled,
            "oidc": settings.oidc.enabled,
            "rules": len(settings.rules),
            "unmatched": settings.unmatched,
            "local_passwords": settings.local_passwords,
            "secrets_changed": bool(
                payload.ldap_bind_password
                or payload.oidc_client_secret
                or payload.clear_ldap_bind_password
                or payload.clear_oidc_client_secret
            ),
        },
        app_id="processcraft",
    )
    return _public(rt)


def _draft(rt: Any, payload: DirectoryPayload):
    """The settings on the page, saved or not, with the saved secret when none was typed."""

    raw = payload.settings or {}
    ldap = dict(raw.get("ldap") or {}) if isinstance(raw.get("ldap"), dict) else {}
    oidc = dict(raw.get("oidc") or {}) if isinstance(raw.get("oidc"), dict) else {}
    # A test runs whether or not the method is on yet.
    return _checked(
        rt,
        {**raw, "ldap": {**ldap, "enabled": False}, "oidc": {**oidc, "enabled": False}},
        strict=False,
    )


@router.post("/api/directory/ldap/test")
def test_ldap(payload: LdapTest, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Connects with the page's settings; with a username, finds the person and maps their access."""

    settings = _draft(rt, payload)
    if not settings.ldap.urls or not settings.ldap.base_dn:
        raise HTTPException(
            status_code=422, detail=t("Fill in the server and the search base first.")
        )
    _secret_follows(
        rt,
        "ldap_bind_password",
        _ldap_target(rt.directory.settings()),
        _ldap_target(settings),
        payload.ldap_bind_password,
        payload.clear_ldap_bind_password,
    )
    bind_password = (
        ""
        if payload.clear_ldap_bind_password
        else payload.ldap_bind_password or rt.directory.secrets.get("ldap_bind_password") or ""
    )
    report = LdapDirectory(settings.ldap, bind_password, connect=rt.directory.ldap_connect).test(
        payload.username, payload.password
    )
    person = report.get("person")
    if person is not None:
        access = map_access(settings, tuple(person["groups"]))
        report["access"] = access.as_dict() if access else None
    return report


@router.post("/api/directory/oidc/test")
def test_oidc(payload: DirectoryPayload, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Reaches the provider with the page's settings: its configuration and signing keys."""

    settings = _draft(rt, payload)
    if not settings.oidc.issuer:
        raise HTTPException(status_code=422, detail=t("Fill in the provider address first."))
    return rt.directory.oidc(settings).test()


@router.post("/api/directory/preview")
def preview(payload: MappingPreview, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The access the page's rules give someone in these directory groups."""

    settings = _checked(rt, payload.settings, strict=False)
    access = map_access(settings, tuple(str(group) for group in payload.groups))
    return {"access": access.as_dict() if access else None}
