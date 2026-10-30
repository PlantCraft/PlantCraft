"""Signing in against LDAP or Active Directory: find the person with the service account, prove
their password with a bind as them, read their groups and attributes.

Always over TLS (LDAPS or StartTLS), with the server's certificate checked against the system's
authorities or the CA certificate pasted in Settings. Read-only: nothing is ever written to the
directory.
"""

from __future__ import annotations

import ssl
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from ldap3 import NONE, Connection, Server, ServerPool, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from plantcraft.directory.mapping import (
    DirectoryPerson,
    DirectoryRefused,
    DirectoryUnavailable,
    WrongCredentials,
)
from plantcraft.directory.settings import LdapSettings
from plantcraft.i18n import t

INVALID_CREDENTIALS = 49
WRONG = "Incorrect username or password."

ConnectionFactory = Callable[[LdapSettings, str, str], Any]


def _tls(settings: LdapSettings) -> Tls:
    return Tls(
        validate=ssl.CERT_REQUIRED if settings.verify_certificate else ssl.CERT_NONE,
        version=ssl.PROTOCOL_TLS_CLIENT,
        ca_certs_data=settings.ca_certificate or None,
    )


def open_connection(settings: LdapSettings, user: str, password: str) -> Connection:
    """A bound connection (``user`` empty: anonymous), over LDAPS or StartTLS; never in clear."""

    tls = _tls(settings)
    servers = []
    for url in settings.urls:
        parts = urlsplit(url)
        servers.append(
            Server(
                parts.hostname,
                port=parts.port or (636 if parts.scheme == "ldaps" else 389),
                use_ssl=parts.scheme == "ldaps",
                tls=tls,
                get_info=NONE,
                connect_timeout=settings.timeout_seconds,
            )
        )
    pool = ServerPool(servers, "FIRST", active=1, exhaust=False)
    connection = Connection(
        pool,
        user=user or None,
        password=password or None,
        auto_bind="NONE",
        read_only=True,
        receive_timeout=settings.timeout_seconds,
        raise_exceptions=False,
    )
    try:
        connection.open()
        if settings.security == "starttls" and not connection.start_tls():
            raise DirectoryUnavailable(t("The directory refused StartTLS."))
        if settings.security == "ldaps" and not connection.server.ssl:
            raise DirectoryUnavailable(t("The directory refused LDAPS."))
    except LDAPException as exc:
        raise DirectoryUnavailable(_reason(exc)) from exc
    return connection


def _reason(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    if "certificate" in text.lower() or isinstance(exc.__cause__, ssl.SSLError):
        return t(
            "The directory's certificate was not accepted ({error}). Paste the company's CA certificate in Settings.",
            error=text[:200],
        )
    return t("The directory did not answer: {error}", error=text[:200])


def _first(entry: dict[str, Any], name: str) -> str:
    if not name:
        return ""
    for key, values in entry.items():
        if key.lower() == name.lower():
            value = values[0] if isinstance(values, list) and values else values
            if isinstance(value, bytes):
                return value.decode("utf-8", "replace").strip()
            return str(value or "").strip()
    return ""


def _external_id(raw: dict[str, Any], name: str, dn: str) -> str:
    for key, values in raw.items():
        if key.lower() == (name or "").lower() and values:
            value = values[0]
            if isinstance(value, bytes):
                if len(value) == 16 and name.lower() == "objectguid":
                    return str(uuid.UUID(bytes_le=value))
                try:
                    return value.decode("utf-8")
                except UnicodeDecodeError:
                    return value.hex()
            return str(value)
    return dn.lower()


def _bind(connection: Any) -> tuple[bool, int]:
    try:
        ok = bool(connection.bind())
    except LDAPException as exc:
        raise DirectoryUnavailable(_reason(exc)) from exc
    return ok, int((connection.result or {}).get("result") or 0)


class LdapDirectory:
    """One sign-in or test against the directory set in Settings."""

    def __init__(
        self,
        settings: LdapSettings,
        bind_password: str | None,
        *,
        connect: ConnectionFactory | None = None,
    ):
        self.settings = settings
        self.bind_password = bind_password or ""
        self.connect = connect or open_connection

    def _attributes(self) -> list[str]:
        s = self.settings
        names = [
            s.username_attribute,
            s.id_attribute,
            s.display_name_attribute,
            s.email_attribute,
            s.job_title_attribute,
            s.department_attribute,
            s.phone_attribute,
            s.organization_attribute,
            s.unit_attribute,
        ]
        if s.group_mode == "memberof":
            names.append("memberOf")
        return sorted({name for name in names if name})

    def _service(self) -> Any:
        connection = self.connect(self.settings, self.settings.bind_dn, self.bind_password)
        ok, code = _bind(connection)
        if not ok:
            if code == INVALID_CREDENTIALS:
                raise DirectoryUnavailable(
                    t(
                        "The directory refused the service account: check its DN and password in Settings."
                    )
                )
            raise DirectoryUnavailable(
                t("The directory refused the service account (LDAP result {code}).", code=code)
            )
        return connection

    def find(
        self, connection: Any, username: str
    ) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
        """``(dn, attributes, raw attributes)`` of the one person ``username`` names."""

        query = self.settings.user_filter.replace("{username}", escape_filter_chars(username))
        try:
            connection.search(
                self.settings.base_dn,
                query,
                attributes=self._attributes(),
                size_limit=2,
                time_limit=self.settings.timeout_seconds,
            )
        except LDAPException as exc:
            raise DirectoryUnavailable(_reason(exc)) from exc
        found = [
            entry for entry in (connection.response or []) if entry.get("type") == "searchResEntry"
        ]
        if len(found) != 1:
            if len(found) > 1:
                raise DirectoryRefused(
                    t("More than one person matches this username in the directory.")
                )
            return None
        entry = found[0]
        return (
            entry["dn"],
            dict(entry.get("attributes") or {}),
            dict(entry.get("raw_attributes") or {}),
        )

    def groups(
        self, connection: Any, dn: str, username: str, attributes: dict[str, Any]
    ) -> tuple[str, ...]:
        s = self.settings
        if s.group_mode == "memberof":
            values = next((v for k, v in attributes.items() if k.lower() == "memberof"), []) or []
            values = values if isinstance(values, list) else [values]
            return tuple(str(value) for value in values)
        query = s.group_filter.replace("{dn}", escape_filter_chars(dn)).replace(
            "{username}", escape_filter_chars(username)
        )
        try:
            connection.search(
                s.group_base_dn or s.base_dn,
                query,
                attributes=[s.group_name_attribute] if s.group_name_attribute else [],
                time_limit=s.timeout_seconds,
                size_limit=1000,
            )
        except LDAPException as exc:
            raise DirectoryUnavailable(_reason(exc)) from exc
        return tuple(
            entry["dn"]
            for entry in (connection.response or [])
            if entry.get("type") == "searchResEntry"
        )

    def _person(
        self,
        dn: str,
        username: str,
        attributes: dict[str, Any],
        raw: dict[str, Any],
        groups: tuple[str, ...],
    ) -> DirectoryPerson:
        s = self.settings
        return DirectoryPerson(
            source="ldap",
            external_id=_external_id(raw, s.id_attribute, dn),
            username=_first(attributes, s.username_attribute) or username,
            display_name=_first(attributes, s.display_name_attribute),
            groups=groups,
            profile={
                "email": _first(attributes, s.email_attribute),
                "job_title": _first(attributes, s.job_title_attribute),
                "role": _first(attributes, s.department_attribute),
                "phone": _first(attributes, s.phone_attribute),
                "organization": _first(attributes, s.organization_attribute),
                "unit": _first(attributes, s.unit_attribute),
                "affiliation": "internal",
            },
        )

    def authenticate(self, username: str, password: str) -> DirectoryPerson:
        """The person, once the directory accepted their password; ``DirectoryRefused`` if not."""

        username = username.strip()
        # An empty password is an "unauthenticated bind", which many servers accept: never.
        if not username or not password or "\x00" in password or len(username) > 256:
            raise WrongCredentials(t(WRONG))
        service = self._service()
        try:
            found = self.find(service, username)
            if found is None:
                raise WrongCredentials(t(WRONG))
            dn, attributes, raw = found
            person = self.connect(self.settings, dn, password)
            try:
                ok, code = _bind(person)
            finally:
                person.unbind()
            if not ok:
                if code == INVALID_CREDENTIALS:
                    raise WrongCredentials(t(WRONG))
                raise DirectoryUnavailable(
                    t("The directory did not accept the sign-in (LDAP result {code}).", code=code)
                )
            groups = self.groups(service, dn, username, attributes)
        finally:
            service.unbind()
        return self._person(dn, username, attributes, raw, groups)

    def test(self, username: str = "", password: str = "") -> dict[str, Any]:
        """The steps of a sign-in, each with its outcome, for the Settings page's test."""

        steps: list[dict[str, Any]] = []
        report: dict[str, Any] = {"ok": False, "steps": steps, "person": None}
        try:
            service = self._service()
        except DirectoryUnavailable as exc:
            steps.append(
                {
                    "step": t("Connect and sign in with the service account"),
                    "ok": False,
                    "detail": str(exc),
                }
            )
            return report
        steps.append(
            {
                "step": t("Connect and sign in with the service account"),
                "ok": True,
                "detail": t(
                    "Connected over {security}.",
                    security="LDAPS" if self.settings.security == "ldaps" else "StartTLS",
                ),
            }
        )
        try:
            if not username.strip():
                report["ok"] = True
                return report
            found = self.find(service, username.strip())
            if found is None:
                steps.append(
                    {
                        "step": t("Find the person"),
                        "ok": False,
                        "detail": t(
                            "Nobody matches the user filter for {username}.", username=username
                        ),
                    }
                )
                return report
            dn, attributes, raw = found
            steps.append({"step": t("Find the person"), "ok": True, "detail": dn})
            if password:
                person_connection = self.connect(self.settings, dn, password)
                try:
                    ok, code = _bind(person_connection)
                finally:
                    person_connection.unbind()
                steps.append(
                    {
                        "step": t("Check the password"),
                        "ok": ok,
                        "detail": t("Accepted.")
                        if ok
                        else t("Refused (LDAP result {code}).", code=code),
                    }
                )
                if not ok:
                    return report
            groups = self.groups(service, dn, username.strip(), attributes)
            steps.append(
                {
                    "step": t("Read the groups"),
                    "ok": True,
                    "detail": ", ".join(groups) or t("No groups."),
                }
            )
            person = self._person(dn, username.strip(), attributes, raw, groups)
            report["person"] = {
                "username": person.username,
                "external_id": person.external_id,
                "display_name": person.display_name,
                "groups": list(person.groups),
                "profile": person.profile,
            }
            report["ok"] = True
        except (DirectoryRefused, DirectoryUnavailable) as exc:
            steps.append({"step": t("Find the person"), "ok": False, "detail": str(exc)})
        finally:
            service.unbind()
        return report
