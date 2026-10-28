"""Corporate sign-in (docs/corporate-login.md): people sign in with their company account, from
LDAP or Active Directory or through single sign-on with OpenID Connect, instead of an account
created here one by one. The directory's groups become the access, app roles and groups here.

Off by default; the installation's own admin account always signs in with its password, so a
directory that stops answering never locks the admins out.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from processcraft.db import Database
from processcraft.directory.ldap import LdapDirectory
from processcraft.directory.mapping import (
    DirectoryPerson,
    DirectoryRefused,
    DirectoryUnavailable,
    MappedAccess,
    Provisioner,
    WrongCredentials,
    map_access,
)
from processcraft.directory.oidc import OidcClient, new_flow
from processcraft.directory.settings import (
    DirectorySecrets,
    DirectorySettings,
    DirectorySettingsStore,
    check_settings,
    corporate_login_allowed,
)
from processcraft.files import write_atomic

__all__ = [
    "CorporateLogin",
    "DirectoryPerson",
    "DirectoryRefused",
    "DirectorySettings",
    "DirectoryUnavailable",
    "MappedAccess",
    "WrongCredentials",
    "check_settings",
    "corporate_login_allowed",
    "map_access",
    "new_flow",
]


class CorporateLogin:
    """Settings, secrets and the two ways in (LDAP, OIDC) for one installation."""

    def __init__(
        self,
        db: Database,
        users: Any,
        groups: Any,
        secrets: DirectorySecrets,
        data_dir: Path,
        audit: Any | None = None,
    ):
        self.store = DirectorySettingsStore(db)
        self.secrets = secrets
        self.data_dir = Path(data_dir)
        self.provisioner = Provisioner(users, groups, audit)
        # Tests and the live checks swap these for fakes.
        self.ldap_connect: Any = None
        self.oidc_http: Any = None

    def settings(self) -> DirectorySettings:
        return self.store.get()

    def methods(self) -> dict[str, Any]:
        """What the sign-in page offers (no secrets, no addresses)."""

        settings = self.settings()
        return {
            "ldap": settings.method_enabled("ldap"),
            "oidc": settings.method_enabled("oidc"),
            "oidc_label": settings.oidc.label if settings.method_enabled("oidc") else None,
        }

    def ldap(self, settings: DirectorySettings | None = None) -> LdapDirectory:
        settings = settings or self.settings()
        return LdapDirectory(
            settings.ldap, self.secrets.get("ldap_bind_password"), connect=self.ldap_connect
        )

    def _ca_file(self, pem: str) -> Path | None:
        """The pasted CA certificate as a file (``requests`` reads a path), named by its hash."""

        if not pem:
            return None
        digest = hashlib.sha256(pem.encode()).hexdigest()[:16]
        path = self.data_dir / f"directory-ca-{digest}.pem"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(path, pem, mode=0o644)
        return path

    def oidc(self, settings: DirectorySettings | None = None) -> OidcClient:
        settings = settings or self.settings()
        return OidcClient(
            settings.oidc,
            self.secrets.get("oidc_client_secret"),
            ca_file=self._ca_file(settings.oidc.ca_certificate),
            http=self.oidc_http,
        )

    def sign_in(self, person: DirectoryPerson, *, reserved: set[str]) -> str:
        return self.provisioner.sign_in(person, self.settings(), reserved=reserved)

    def ldap_sign_in(self, username: str, password: str, *, reserved: set[str]) -> str:
        """The username to open a session for, once the directory accepted the password."""

        settings = self.settings()
        if not settings.method_enabled("ldap"):
            raise WrongCredentials("off")
        person = self.ldap(settings).authenticate(username, password)
        return self.provisioner.sign_in(person, settings, reserved=reserved)
