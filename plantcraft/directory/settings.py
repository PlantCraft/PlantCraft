"""Corporate sign-in settings: the LDAP or Active Directory server, the OIDC provider, how the
directory's groups become access here, and the two secrets (kept beside the database).

Everything is off by default. ``PLANTCRAFT_CORPORATE_LOGIN=off`` turns it off for good in an
installation (the Settings page then only explains why).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from plantcraft.auth.access import ACCESS_LEVELS
from plantcraft.auth.users import APP_ROLES
from plantcraft.config import env_flag
from plantcraft.db import Database, Store
from plantcraft.files import write_atomic
from plantcraft.i18n import t

UNMATCHED = ("deny", *ACCESS_LEVELS[:-1])  # nobody becomes admin by default
MAX_RULES = 200
MAX_CERTIFICATE = 20_000
SECRET_KEYS = ("ldap_bind_password", "oidc_client_secret")

# What each kind of server usually needs; the Setup page fills these in on "Use defaults for".
LDAP_PRESETS: dict[str, dict[str, str]] = {
    "active_directory": {
        "user_filter": "(&(objectCategory=person)(objectClass=user)"
        "(|(sAMAccountName={username})(userPrincipalName={username})))",
        "username_attribute": "sAMAccountName",
        "id_attribute": "objectGUID",
        "group_mode": "search",
        # Nested groups too (LDAP_MATCHING_RULE_IN_CHAIN), as people expect from AD.
        "group_filter": "(&(objectClass=group)(member:1.2.840.113556.1.4.1941:={dn}))",
        "group_name_attribute": "cn",
        "display_name_attribute": "displayName",
        "email_attribute": "mail",
        "job_title_attribute": "title",
        "department_attribute": "department",
        "phone_attribute": "telephoneNumber",
        "organization_attribute": "company",
        "unit_attribute": "physicalDeliveryOfficeName",
    },
    "openldap": {
        "user_filter": "(&(objectClass=inetOrgPerson)(uid={username}))",
        "username_attribute": "uid",
        "id_attribute": "entryUUID",
        "group_mode": "search",
        "group_filter": "(|(&(objectClass=groupOfNames)(member={dn}))"
        "(&(objectClass=groupOfUniqueNames)(uniqueMember={dn}))"
        "(&(objectClass=posixGroup)(memberUid={username})))",
        "group_name_attribute": "cn",
        "display_name_attribute": "cn",
        "email_attribute": "mail",
        "job_title_attribute": "title",
        "department_attribute": "ou",
        "phone_attribute": "telephoneNumber",
        "organization_attribute": "o",
        "unit_attribute": "l",
    },
}


def corporate_login_allowed() -> bool:
    """False when the installation turned corporate sign-in off for good."""

    return env_flag("PLANTCRAFT_CORPORATE_LOGIN", True)


@dataclass(frozen=True)
class LdapSettings:
    enabled: bool = False
    preset: str = "active_directory"
    # One or more servers, separated by spaces (tried in order): ldaps://dc1.company.local
    url: str = ""
    # Never in clear: LDAPS (port 636) or StartTLS on the plain port (389).
    security: str = "ldaps"
    verify_certificate: bool = True
    ca_certificate: str = ""
    # The account that looks people up (read-only); empty for a directory open to search.
    bind_dn: str = ""
    base_dn: str = ""
    user_filter: str = LDAP_PRESETS["active_directory"]["user_filter"]
    username_attribute: str = "sAMAccountName"
    id_attribute: str = "objectGUID"
    # memberof: the person's ``memberOf`` attribute; search: groups whose members include them.
    group_mode: str = "search"
    group_base_dn: str = ""
    group_filter: str = LDAP_PRESETS["active_directory"]["group_filter"]
    group_name_attribute: str = "cn"
    display_name_attribute: str = "displayName"
    email_attribute: str = "mail"
    job_title_attribute: str = "title"
    department_attribute: str = "department"
    phone_attribute: str = "telephoneNumber"
    organization_attribute: str = "company"
    unit_attribute: str = "physicalDeliveryOfficeName"
    timeout_seconds: int = 5

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.urls) and bool(self.base_dn)

    @property
    def urls(self) -> list[str]:
        return [item for item in self.url.split() if item]


@dataclass(frozen=True)
class OidcSettings:
    enabled: bool = False
    # The button on the sign-in page: "Sign in with <label>".
    label: str = "company account"
    issuer: str = ""
    client_id: str = ""
    scopes: str = "openid profile email"
    username_claim: str = "preferred_username"
    groups_claim: str = "groups"
    display_name_claim: str = "name"
    email_claim: str = "email"
    job_title_claim: str = ""
    department_claim: str = ""
    # PlantCraft's address as people open it (https://processcraft.company.local): the
    # provider sends the browser back to <address>/api/sso/oidc/callback.
    public_url: str = ""
    verify_certificate: bool = True
    ca_certificate: str = ""

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.issuer and self.client_id and self.public_url)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url.rstrip('/')}/api/sso/oidc/callback" if self.public_url else ""


@dataclass(frozen=True)
class GroupRule:
    """People in the directory group ``match`` get this access here (the highest rule wins)."""

    match: str
    level: str = "viewer"
    # None: every app; a list: these apps.
    apps: tuple[str, ...] | None = None
    app_roles: tuple[tuple[str, str], ...] = ()
    groups: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "match": self.match,
            "level": self.level,
            "apps": None if self.apps is None else list(self.apps),
            "app_roles": dict(self.app_roles),
            "groups": list(self.groups),
        }


@dataclass(frozen=True)
class DirectorySettings:
    ldap: LdapSettings = field(default_factory=LdapSettings)
    oidc: OidcSettings = field(default_factory=OidcSettings)
    rules: tuple[GroupRule, ...] = ()
    # People in no mapped group: refused ("deny") or given this level.
    unmatched: str = "deny"
    # People from the directory sign in again after this long, so a person turned off there
    # loses access here within the day.
    session_hours: int = 12
    # False: only the installation's own admin account signs in with a password kept here.
    local_passwords: bool = True

    def method_enabled(self, source: str) -> bool:
        if not corporate_login_allowed():
            return False
        if source == "ldap":
            return self.ldap.ready
        if source == "oidc":
            return self.oidc.ready
        return False

    def public(self, secrets: dict[str, bool]) -> dict[str, Any]:
        return {
            "ldap": {
                **asdict(self.ldap),
                "ready": self.ldap.ready,
                "has_bind_password": secrets["ldap_bind_password"],
            },
            "oidc": {
                **asdict(self.oidc),
                "ready": self.oidc.ready,
                "redirect_uri": self.oidc.redirect_uri,
                "has_client_secret": secrets["oidc_client_secret"],
            },
            "rules": [rule.as_dict() for rule in self.rules],
            "unmatched": self.unmatched,
            "session_hours": self.session_hours,
            "local_passwords": self.local_passwords,
            "allowed": corporate_login_allowed(),
            "presets": LDAP_PRESETS,
        }


# Checking ------------------------------------------------------------------------------------

_ATTRIBUTE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$|^$")
_CLAIM = re.compile(r"^[A-Za-z0-9_:./-]{0,100}$")


def _text(payload: dict[str, Any], key: str, default: str, limit: int) -> str:
    value = payload.get(key, default)
    value = "" if value is None else str(value).strip()
    if len(value) > limit:
        raise ValueError(t("{field} is longer than {count} characters.", field=key, count=limit))
    return value


def _flag(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    return value if isinstance(value, bool) else default


def _certificate(payload: dict[str, Any]) -> str:
    pem = _text(payload, "ca_certificate", "", MAX_CERTIFICATE)
    if pem and "-----BEGIN CERTIFICATE-----" not in pem:
        raise ValueError(
            t("The CA certificate is the PEM text that starts with -----BEGIN CERTIFICATE-----.")
        )
    return pem


def _filter(value: str, name: str) -> str:
    if value and (not value.startswith("(") or value.count("(") != value.count(")")):
        raise ValueError(t("The {name} is an LDAP filter in parentheses.", name=name))
    return value


def check_ldap(payload: dict[str, Any]) -> LdapSettings:
    base = LdapSettings()
    values: dict[str, Any] = {}
    for item in fields(LdapSettings):
        default = getattr(base, item.name)
        if isinstance(default, bool):
            values[item.name] = _flag(payload, item.name, default)
        elif isinstance(default, int):
            try:
                values[item.name] = min(30, max(1, int(payload.get(item.name, default))))
            except (TypeError, ValueError):
                values[item.name] = default
        elif item.name == "ca_certificate":
            values[item.name] = _certificate(payload)
        else:
            values[item.name] = _text(payload, item.name, default, 1000)
    settings = LdapSettings(**values)
    if settings.preset not in LDAP_PRESETS:
        raise ValueError(t("Choose Active Directory or OpenLDAP."))
    if settings.security not in ("ldaps", "starttls"):
        raise ValueError(
            t("The directory is reached over LDAPS or StartTLS: passwords never travel in clear.")
        )
    for url in settings.urls:
        parts = urlsplit(url)
        if parts.scheme not in ("ldap", "ldaps") or not parts.hostname:
            raise ValueError(t("A directory server is ldaps://host or ldap://host."))
        try:
            parts.port  # noqa: B018 (validates the port)
        except ValueError as exc:
            raise ValueError(t("A directory server is ldaps://host or ldap://host.")) from exc
        if settings.security == "ldaps" and parts.scheme != "ldaps":
            raise ValueError(t("With LDAPS, every server starts with ldaps://."))
        if settings.security == "starttls" and parts.scheme != "ldap":
            raise ValueError(
                t("With StartTLS, every server starts with ldap:// (usually port 389).")
            )
    if settings.group_mode not in ("memberof", "search"):
        raise ValueError(t("Groups come from memberOf or from a group search."))
    _filter(settings.user_filter, t("user filter"))
    _filter(settings.group_filter, t("group filter"))
    if settings.enabled and "{username}" not in settings.user_filter:
        raise ValueError(t("The user filter needs {username}, where the typed name goes."))
    for item in fields(LdapSettings):
        if item.name.endswith("_attribute") and not _ATTRIBUTE.match(getattr(settings, item.name)):
            raise ValueError(t("{field} is not an LDAP attribute name.", field=item.name))
    if settings.enabled and not settings.ready:
        raise ValueError(t("To turn LDAP on, fill in the server and the search base."))
    if not settings.username_attribute:
        raise ValueError(t("{field} is not an LDAP attribute name.", field="username_attribute"))
    return settings


def _https_url(value: str, name: str, *, allow_http: bool = False) -> str:
    if not value:
        return value
    parts = urlsplit(value)
    schemes = ("https", "http") if allow_http else ("https",)
    if parts.scheme not in schemes or not parts.hostname or parts.query or parts.fragment:
        raise ValueError(t("The {name} is an https:// address.", name=name))
    return value.rstrip("/")


def check_oidc(payload: dict[str, Any]) -> OidcSettings:
    base = OidcSettings()
    values: dict[str, Any] = {}
    for item in fields(OidcSettings):
        default = getattr(base, item.name)
        if isinstance(default, bool):
            values[item.name] = _flag(payload, item.name, default)
        elif item.name == "ca_certificate":
            values[item.name] = _certificate(payload)
        else:
            values[item.name] = _text(payload, item.name, default, 500)
    settings = OidcSettings(**values)
    # An identity provider inside the plant's network may run on plain http only in a lab:
    # PlantCraft refuses it in the address of the provider, which carries the tokens.
    settings = replace(
        settings,
        issuer=_https_url(settings.issuer, t("provider address")),
        public_url=_https_url(settings.public_url, t("PlantCraft address"), allow_http=True),
        label=settings.label or base.label,
    )
    if "openid" not in settings.scopes.split():
        raise ValueError(t("The scopes must include openid."))
    for item in fields(OidcSettings):
        if item.name.endswith("_claim") and not _CLAIM.match(getattr(settings, item.name)):
            raise ValueError(t("{field} is not a claim name.", field=item.name))
    if not settings.username_claim:
        raise ValueError(t("{field} is not a claim name.", field="username_claim"))
    if settings.enabled and not settings.ready:
        raise ValueError(
            t(
                "To turn OIDC on, fill in the provider address, the client id and PlantCraft's address."
            )
        )
    return settings


def check_rules(
    raw: Any, app_ids: set[str] | None, group_ids: set[str] | None
) -> tuple[GroupRule, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_RULES:
        raise ValueError(t("At most {count} group rules.", count=MAX_RULES))
    rules = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(t("Invalid group rule."))
        match = str(item.get("match") or "").strip()
        if not match or len(match) > 500:
            raise ValueError(
                t("Each rule needs the directory group's name (up to 500 characters).")
            )
        level = str(item.get("level") or "viewer")
        if level not in ACCESS_LEVELS:
            raise ValueError(
                t(
                    "Invalid access level: {level}. Use {levels}.",
                    level=level,
                    levels=", ".join(ACCESS_LEVELS),
                )
            )
        apps_raw = item.get("apps")
        apps = None
        if apps_raw is not None:
            if not isinstance(apps_raw, list):
                raise ValueError(t("Invalid group rule."))
            apps = tuple(sorted({str(app) for app in apps_raw}))
            unknown = sorted(set(apps) - app_ids) if app_ids is not None else []
            if unknown:
                raise ValueError(t("Unknown app: {app}.", app=unknown[0]))
        roles_raw = item.get("app_roles") or {}
        if not isinstance(roles_raw, dict) or any(
            value not in APP_ROLES for value in roles_raw.values()
        ):
            raise ValueError(t("An app role is viewer or editor."))
        groups = tuple(dict.fromkeys(str(group) for group in (item.get("groups") or [])))
        missing = sorted(set(groups) - group_ids) if group_ids is not None else []
        if missing:
            raise ValueError(t("Group not found: {group}.", group=missing[0]))
        rules.append(
            GroupRule(
                match=match,
                level=level,
                apps=apps,
                app_roles=tuple(sorted((str(key), str(value)) for key, value in roles_raw.items())),
                groups=groups,
            )
        )
    return tuple(rules)


def check_settings(
    payload: dict[str, Any], *, app_ids: set[str] | None = None, group_ids: set[str] | None = None
) -> DirectorySettings:
    unmatched = str(payload.get("unmatched") or "deny")
    if unmatched not in UNMATCHED:
        raise ValueError(
            t("People in no mapped group are refused or get viewer, editor or dashboards access.")
        )
    try:
        hours = min(24 * 7, max(1, int(payload.get("session_hours") or 12)))
    except (TypeError, ValueError):
        hours = 12
    return DirectorySettings(
        ldap=check_ldap(payload.get("ldap") if isinstance(payload.get("ldap"), dict) else {}),
        oidc=check_oidc(payload.get("oidc") if isinstance(payload.get("oidc"), dict) else {}),
        rules=check_rules(payload.get("rules"), app_ids, group_ids),
        unmatched=unmatched,
        session_hours=hours,
        local_passwords=_flag(payload, "local_passwords", True),
    )


def _stored(data: dict[str, Any]) -> DirectorySettings:
    """Settings as saved; a row that no longer passes the checks falls back to everything off."""

    try:
        return check_settings(data)
    except (ValueError, TypeError):
        return DirectorySettings()


class DirectorySecrets:
    """The LDAP service account's password and the OIDC client secret, in a JSON file with mode
    600 beside the database (never in it, never sent back to the browser)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {
            key: str(data[key]) for key in SECRET_KEYS if isinstance(data, dict) and data.get(key)
        }

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._read().get(key)

    def present(self) -> dict[str, bool]:
        with self._lock:
            data = self._read()
        return {key: bool(data.get(key)) for key in SECRET_KEYS}

    def set(self, key: str, value: str | None) -> None:
        if key not in SECRET_KEYS:
            raise KeyError(key)
        with self._lock:
            data = self._read()
            if value:
                data[key] = value
            else:
                data.pop(key, None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, json.dumps(data))


class DirectorySettingsStore(Store):
    """The one row of corporate sign-in settings."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS directory_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
    """

    def __init__(self, db: Database):
        super().__init__(db)

    def get(self) -> DirectorySettings:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM directory_settings WHERE id = 1"
            ).fetchone()
        if not row:
            return DirectorySettings()
        try:
            data = json.loads(row["payload_json"])
        except ValueError:
            return DirectorySettings()
        return _stored(data if isinstance(data, dict) else {})

    def save(self, settings: DirectorySettings, username: str) -> None:
        payload = {
            "ldap": asdict(settings.ldap),
            "oidc": asdict(settings.oidc),
            "rules": [rule.as_dict() for rule in settings.rules],
            "unmatched": settings.unmatched,
            "session_hours": settings.session_hours,
            "local_passwords": settings.local_passwords,
        }
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO directory_settings (id, payload_json, updated_at, updated_by)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at, updated_by = excluded.updated_by
                """,
                (json.dumps(payload, ensure_ascii=False), self._now(), username),
            )
