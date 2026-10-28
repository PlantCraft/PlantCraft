"""Checking an OpenID Connect ID token against the provider's published keys (JWKS), with joserfc.

Only asymmetric algorithms: RS256/384/512, PS256/384/512, ES256/384/512 and EdDSA. ``none`` and
the HMAC family (keyed with the client secret) are refused, so a token cannot be forged by
someone who knows a secret or by dropping the signature. joserfc (BSD-3, the JOSE library of
Authlib's author, which Authlib itself moves to) checks the signature and the claims.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from joserfc import jws, jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

ALGORITHMS = (
    "RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA",
)  # fmt: skip
# The kinds of key those algorithms use (an encryption key or a symmetric one is never tried).
_KEY_TYPES = ("RSA", "EC", "OKP")


class InvalidToken(Exception):
    pass


def header(token: str) -> dict[str, Any]:
    """The token's header, read without checking anything (to see which key it names)."""

    try:
        return dict(jws.extract_compact(token.encode("ascii")).protected)
    except (JoseError, ValueError, TypeError, AttributeError) as exc:
        raise InvalidToken("malformed token") from exc


def _key_set(keys: Iterable[Mapping[str, Any]]) -> KeySet:
    usable = [
        dict(key) for key in keys if key.get("kty") in _KEY_TYPES and key.get("use", "sig") == "sig"
    ]
    if not usable:
        raise InvalidToken("no published key matches the token")
    try:
        return KeySet.import_key_set({"keys": usable})
    except (JoseError, ValueError, TypeError) as exc:
        raise InvalidToken(f"the published keys do not load ({exc})") from exc


def verify(token: str, keys: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The claims of ``token`` once one of ``keys`` checks its signature."""

    alg = str(header(token).get("alg") or "")
    if alg not in ALGORITHMS:
        raise InvalidToken(f"algorithm {alg!r} is not accepted")
    try:
        return dict(jwt.decode(token, _key_set(keys), algorithms=list(ALGORITHMS)).claims)
    except InvalidToken:
        raise
    except (JoseError, ValueError, TypeError, KeyError) as exc:
        raise InvalidToken(f"bad signature ({exc})") from exc


def check_claims(
    claims: Mapping[str, Any], *, issuer: str, client_id: str, nonce: str, leeway: int
) -> list[str]:
    """The names of the ID token claims that fail (OpenID Connect Core 3.1.3.7); empty when good."""

    issuers = sorted({issuer, issuer.rstrip("/"), issuer.rstrip("/") + "/"})
    registry = jwt.JWTClaimsRegistry(
        leeway=leeway,
        iss={"essential": True, "values": issuers},
        aud={"essential": True, "value": client_id},
        sub={"essential": True},
        exp={"essential": True},
        nonce={"essential": True, "value": nonce},
    )
    problems: list[str] = []
    if not nonce:
        problems.append("nonce")
    try:
        registry.validate(dict(claims))
    except JoseError as exc:
        # The registry stops at the first claim that fails and names it.
        problems.append(str(getattr(exc, "claim", "") or exc.error))
    audience = claims.get("aud")
    if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != client_id:
        problems.append("azp")
    return problems
