"""Single sign-on with OpenID Connect (Keycloak, Microsoft Entra ID, AD FS, Okta and others): the
authorization code flow with PKCE, a ``state`` against forged callbacks and a ``nonce`` against
replayed tokens, and the ID token checked against the provider's published keys.

The provider is reached only at the address set in Settings (in the plant's network, as a rule);
nothing else goes out. Its configuration and keys are cached for an hour in each process; what
must survive between the redirect and the callback (state, nonce, PKCE verifier) travels in the
signed session cookie, so the callback may land on any server process.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from processcraft.directory import jose
from processcraft.directory.mapping import DirectoryPerson, DirectoryRefused, DirectoryUnavailable
from processcraft.directory.settings import OidcSettings
from processcraft.i18n import t

CACHE_SECONDS = 3600
# A key the cache does not know (the provider rotated its keys) fetches them again, at most this
# often, so made-up ``kid`` values cannot turn PlantCraft into a flood against the provider.
REFETCH_SECONDS = 60
LEEWAY_SECONDS = 120
TIMEOUT_SECONDS = 8

_cache: dict[tuple[str, str], tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def new_flow() -> dict[str, str]:
    """``state``, ``nonce`` and the PKCE ``verifier`` of one sign-in (kept in the session)."""

    return {
        "state": secrets.token_urlsafe(24),
        "nonce": secrets.token_urlsafe(24),
        "verifier": secrets.token_urlsafe(48),
    }


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def claim(claims: dict[str, Any], name: str) -> Any:
    """A claim by name, or by a dotted path into nested claims ("realm_access.roles")."""

    if not name:
        return None
    if name in claims:
        return claims[name]
    value: Any = claims
    for part in name.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _groups(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if isinstance(item, (str, int)))[:1000]
    return ()


class OidcClient:
    def __init__(
        self,
        settings: OidcSettings,
        client_secret: str | None,
        *,
        ca_file: Path | None = None,
        http: Any | None = None,
    ):
        self.settings = settings
        self.client_secret = client_secret or ""
        self.http = http or requests.Session()
        if not settings.verify_certificate:
            self.verify: bool | str = False
        elif ca_file is not None:
            self.verify = str(ca_file)
        else:
            self.verify = True

    # The provider's published configuration and keys -------------------------------------

    def _get(self, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.http.get(url, timeout=TIMEOUT_SECONDS, verify=self.verify, **kwargs)
        except requests.exceptions.SSLError as exc:
            raise DirectoryUnavailable(
                t(
                    "The provider's certificate was not accepted. Paste the company's CA certificate in Settings."
                )
            ) from exc
        except requests.RequestException as exc:
            raise DirectoryUnavailable(
                t("The sign-in provider did not answer: {error}", error=str(exc)[:200])
            ) from exc
        if response.status_code != 200:
            raise DirectoryUnavailable(
                t(
                    "The sign-in provider answered {code} at {url}.",
                    code=response.status_code,
                    url=url,
                )
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise DirectoryUnavailable(
                t("The sign-in provider did not answer JSON at {url}.", url=url)
            ) from exc
        if not isinstance(data, dict):
            raise DirectoryUnavailable(
                t("The sign-in provider did not answer JSON at {url}.", url=url)
            )
        return data

    def _cached(self, kind: str, fetch: Any, *, fresh: bool = False) -> Any:
        key = (kind, f"{self.settings.issuer}|{self.verify}")
        now = time.monotonic()
        with _cache_lock:
            hit = _cache.get(key)
        if hit and not fresh and now - hit[0] < CACHE_SECONDS:
            return hit[1]
        if hit and fresh and now - hit[0] < REFETCH_SECONDS:
            return hit[1]
        value = fetch()
        with _cache_lock:
            _cache[key] = (now, value)
        return value

    def discover(self) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            config = self._get(f"{self.settings.issuer}/.well-known/openid-configuration")
            if str(config.get("issuer") or "").rstrip("/") != self.settings.issuer.rstrip("/"):
                raise DirectoryUnavailable(
                    t(
                        "The provider says its address is {found}, not {expected}.",
                        found=config.get("issuer"),
                        expected=self.settings.issuer,
                    )
                )
            for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not str(config.get(name) or "").startswith(("https://", "http://")):
                    raise DirectoryUnavailable(
                        t("The provider's configuration has no {name}.", name=name)
                    )
            return config

        return self._cached("config", fetch)

    def keys(self, *, fresh: bool = False) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            data = self._get(self.discover()["jwks_uri"])
            keys = data.get("keys")
            return [key for key in keys if isinstance(key, dict)] if isinstance(keys, list) else []

        return self._cached("jwks", fetch, fresh=fresh)

    # The flow --------------------------------------------------------------------------

    def authorization_url(self, flow: dict[str, str]) -> str:
        config = self.discover()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.client_id,
                "redirect_uri": self.settings.redirect_uri,
                "scope": self.settings.scopes,
                "state": flow["state"],
                "nonce": flow["nonce"],
                "code_challenge": challenge(flow["verifier"]),
                "code_challenge_method": "S256",
            }
        )
        endpoint = config["authorization_endpoint"]
        return f"{endpoint}{'&' if urlsplit(endpoint).query else '?'}{query}"

    def _exchange(self, code: str, verifier: str) -> dict[str, Any]:
        config = self.discover()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.redirect_uri,
            "code_verifier": verifier,
            "client_id": self.settings.client_id,
        }
        auth = (self.settings.client_id, self.client_secret) if self.client_secret else None
        try:
            response = self.http.post(
                config["token_endpoint"],
                data=form,
                auth=auth,
                timeout=TIMEOUT_SECONDS,
                verify=self.verify,
            )
        except requests.RequestException as exc:
            raise DirectoryUnavailable(
                t("The sign-in provider did not answer: {error}", error=str(exc)[:200])
            ) from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200 or not isinstance(data, dict) or not data.get("id_token"):
            error = (data or {}).get("error") if isinstance(data, dict) else None
            raise DirectoryRefused(
                t(
                    "The sign-in provider did not complete the sign-in ({error}).",
                    error=error or response.status_code,
                )
            )
        return data

    def check_id_token(self, token: str, nonce: str) -> dict[str, Any]:
        known = {key.get("kid") for key in self.keys()}
        try:
            claims = jose.verify(token, self.keys(fresh=jose.header(token).get("kid") not in known))
        except jose.InvalidToken:
            # The provider may have replaced a key under the same id: read its keys once more.
            try:
                claims = jose.verify(token, self.keys(fresh=True))
            except jose.InvalidToken as exc:
                raise DirectoryRefused(
                    t("The provider's ID token was not accepted ({error}).", error=str(exc))
                ) from exc
        problems = jose.check_claims(
            claims,
            issuer=self.settings.issuer,
            client_id=self.settings.client_id,
            nonce=nonce,
            leeway=LEEWAY_SECONDS,
        )
        if not _text(claims.get("sub")) and "sub" not in problems:
            problems.append("sub")
        if problems:
            raise DirectoryRefused(
                t("The provider's ID token was not accepted ({error}).", error=", ".join(problems))
            )
        return claims

    def _userinfo(self, access_token: str, subject: str) -> dict[str, Any]:
        endpoint = self.discover().get("userinfo_endpoint")
        if not access_token or not isinstance(endpoint, str) or not endpoint:
            return {}
        try:
            info = self._get(endpoint, headers={"Authorization": f"Bearer {access_token}"})
        except DirectoryUnavailable:
            return {}
        # Only the same person's details (OpenID Connect Core, 5.3.2).
        return info if info.get("sub") == subject else {}

    def finish(self, code: str, flow: dict[str, str]) -> DirectoryPerson:
        """The person the provider signed in, from the callback's ``code``."""

        tokens = self._exchange(code, flow["verifier"])
        claims = self.check_id_token(str(tokens["id_token"]), flow["nonce"])
        s = self.settings
        wanted = [s.username_claim, s.groups_claim, s.display_name_claim, s.email_claim]
        if any(name and claim(claims, name) is None for name in wanted):
            claims = {
                **self._userinfo(str(tokens.get("access_token") or ""), claims["sub"]),
                **claims,
            }
        return self.person(claims)

    def person(self, claims: dict[str, Any]) -> DirectoryPerson:
        s = self.settings
        username = _text(claim(claims, s.username_claim))
        if not username:
            raise DirectoryRefused(
                t(
                    "The provider sent no {claim} for this person: check the username claim in Settings.",
                    claim=s.username_claim,
                )
            )
        return DirectoryPerson(
            source="oidc",
            external_id=_text(claims.get("sub")),
            username=username,
            display_name=_text(claim(claims, s.display_name_claim)),
            groups=_groups(claim(claims, s.groups_claim)),
            profile={
                "email": _text(claim(claims, s.email_claim)),
                "job_title": _text(claim(claims, s.job_title_claim)),
                "role": _text(claim(claims, s.department_claim)),
                "affiliation": "internal",
            },
        )

    def test(self) -> dict[str, Any]:
        """Reach the provider, read its configuration and keys: the Settings page's test."""

        steps: list[dict[str, Any]] = []
        report: dict[str, Any] = {
            "ok": False,
            "steps": steps,
            "redirect_uri": self.settings.redirect_uri,
        }
        try:
            # A test reads the provider afresh (an admin just changed its keys or address).
            with _cache_lock:
                _cache.pop(("config", f"{self.settings.issuer}|{self.verify}"), None)
                _cache.pop(("jwks", f"{self.settings.issuer}|{self.verify}"), None)
            config = self.discover()
            steps.append(
                {
                    "step": t("Read the provider's configuration"),
                    "ok": True,
                    "detail": config.get("authorization_endpoint"),
                }
            )
            keys = self.keys()
            steps.append(
                {
                    "step": t("Read the provider's signing keys"),
                    "ok": bool(keys),
                    "detail": t("{count} keys.", count=len(keys)),
                }
            )
            methods = config.get("code_challenge_methods_supported")
            if isinstance(methods, list) and "S256" not in methods:
                steps.append(
                    {
                        "step": t("PKCE"),
                        "ok": False,
                        "detail": t("The provider does not offer PKCE (S256)."),
                    }
                )
                return report
            report["ok"] = bool(keys)
        except DirectoryUnavailable as exc:
            steps.append(
                {"step": t("Read the provider's configuration"), "ok": False, "detail": str(exc)}
            )
        return report
