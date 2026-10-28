"""A company directory and a sign-in provider in memory, for the corporate sign-in tests.

``FakeDirectory``: an LDAP directory on ldap3's mock strategy (binds check ``userPassword``).
``FakeProvider``: an OpenID Connect provider answering ``requests``-style calls, signing its ID
tokens with its own RSA key. The live tests run the same journeys against OpenLDAP and Keycloak
(``tests/test_corporate_login_live.py``).
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from ldap3 import MOCK_SYNC, Connection, Server

BASE = "dc=plant,dc=test"
SERVICE_DN = f"uid=reader,ou=people,{BASE}"
SERVICE_PASSWORD = "reader-service-pass"
ISSUER = "https://sso.plant.test/realms/plant"
CLIENT_ID = "processcraft"
CLIENT_SECRET = "processcraft-test-secret"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int(value: int) -> str:
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


class FakeDirectory:
    """People and groups (``groupOfNames``) under ``dc=plant,dc=test``."""

    def __init__(self) -> None:
        self.server = Server("fake-directory")
        self.down = False
        setup = self.connect(None, "", "")
        for dn, attributes in (
            (
                SERVICE_DN,
                {
                    "objectClass": ["inetOrgPerson"],
                    "uid": "reader",
                    "cn": "Reader",
                    "sn": "R",
                    "userPassword": SERVICE_PASSWORD,
                },
            ),
        ):
            setup.strategy.add_entry(dn, attributes)
        self.setup = setup

    def add_person(
        self, uid: str, password: str, *, groups: tuple[str, ...] = (), **attributes: Any
    ) -> str:
        dn = f"uid={uid},ou=people,{BASE}"
        self.setup.strategy.add_entry(
            dn,
            {
                "objectClass": ["inetOrgPerson"],
                "uid": uid,
                "sn": uid,
                "userPassword": password,
                "entryUUID": f"uuid-{uid}",
                **attributes,
            },
        )
        for group in groups:
            self.setup.strategy.add_entry(
                f"cn={group},ou=groups,{BASE}",
                {"objectClass": ["groupOfNames"], "cn": group, "member": [dn]},
            )
        return dn

    def connect(self, _settings: Any, user: str, password: str) -> Connection:
        if self.down:
            from processcraft.directory import DirectoryUnavailable

            raise DirectoryUnavailable("The directory did not answer: connection refused")
        return Connection(
            self.server,
            user=user or None,
            password=password or None,
            client_strategy=MOCK_SYNC,
            raise_exceptions=False,
        )


def ldap_settings(**changes: Any) -> dict[str, Any]:
    from processcraft.directory.settings import LDAP_PRESETS

    return {
        **LDAP_PRESETS["openldap"],
        # The mock strategy knows groupOfNames only.
        "group_filter": "(&(objectClass=groupOfNames)(member={dn}))",
        "preset": "openldap",
        "enabled": True,
        "url": "ldaps://ldap.plant.test",
        "security": "ldaps",
        "bind_dn": SERVICE_DN,
        "base_dn": BASE,
        **changes,
    }


class _Reply:
    def __init__(self, status: int, body: Any):
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        return self._body


class FakeProvider:
    """An OpenID Connect provider: discovery, keys, the code exchange and user info."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "key-1"
        self.codes: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        # What the next ID token carries differently (a test of each check).
        self.tamper: dict[str, Any] = {}
        self.userinfo: dict[str, Any] = {}

    # The browser's side ---------------------------------------------------------------

    def sign_in(self, authorization_url: str, claims: dict[str, Any]) -> tuple[str, str]:
        """The person signs in at the provider: returns the callback's ``(code, state)``."""

        query = {
            key: values[0] for key, values in parse_qs(urlsplit(authorization_url).query).items()
        }
        assert query["client_id"] == CLIENT_ID and query["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(16)
        self.codes[code] = {"claims": claims, **query}
        return code, query["state"]

    # requests-style calls ------------------------------------------------------------

    def get(self, url: str, **kwargs: Any) -> _Reply:
        self.calls.append(f"GET {url}")
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return _Reply(
                200,
                {
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/auth",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/certs",
                    "userinfo_endpoint": f"{ISSUER}/userinfo",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if url == f"{ISSUER}/certs":
            numbers = self.key.public_key().public_numbers()
            return _Reply(
                200,
                {
                    "keys": [
                        {
                            "kty": "RSA",
                            "kid": self.kid,
                            "use": "sig",
                            "alg": "RS256",
                            "n": _int(numbers.n),
                            "e": _int(numbers.e),
                        }
                    ]
                },
            )
        if url == f"{ISSUER}/userinfo":
            return _Reply(200, self.userinfo)
        return _Reply(404, {})

    def post(self, url: str, data: dict[str, Any], auth: Any = None, **kwargs: Any) -> _Reply:
        self.calls.append(f"POST {url}")
        if url != f"{ISSUER}/token":
            return _Reply(404, {})
        grant = self.codes.pop(data.get("code"), None)
        if grant is None or auth != (CLIENT_ID, CLIENT_SECRET):
            return _Reply(400, {"error": "invalid_grant"})
        verifier = data["code_verifier"].encode("ascii")
        digest = hashes.Hash(hashes.SHA256())
        digest.update(verifier)
        if (
            b64(digest.finalize()) != grant["code_challenge"]
            or data["redirect_uri"] != grant["redirect_uri"]
        ):
            return _Reply(400, {"error": "invalid_grant"})
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            "nonce": grant["nonce"],
            **grant["claims"],
            **self.tamper,
        }
        return _Reply(
            200,
            {
                "id_token": self.id_token(claims),
                "access_token": "access-token",
                "token_type": "Bearer",
            },
        )

    def id_token(self, claims: dict[str, Any], *, alg: str = "RS256") -> str:
        header = b64(json.dumps({"alg": alg, "kid": self.kid, "typ": "JWT"}).encode())
        body = b64(json.dumps(claims).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        signature = self.key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{header}.{body}.{b64(signature)}"


def oidc_settings(**changes: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "label": "Test Company",
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "public_url": "http://testserver",
        **changes,
    }
