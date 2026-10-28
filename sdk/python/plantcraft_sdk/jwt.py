"""JSON Web Tokens signed with Ed25519 (``alg: EdDSA``), checked by PyJWT.

PlantCraft signs; apps verify offline with the public keys it lists at
``GET /api/v1/auth/keys`` (JWK, ``kty: OKP``, ``crv: Ed25519``)::

    token = encode({"sub": "ana", "aud": "linkcraft", "exp": ...}, private_key, kid="k1")
    claims = decode(token, jwks, audience="linkcraft")

One algorithm only (EdDSA; ``none`` and every other one are refused before PyJWT is asked).
Every failure raises a subclass of ``TokenError`` with a message a person can act on.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ALGORITHM = "EdDSA"
ISSUER = "processcraft"
# Clock difference tolerated between PlantCraft and an app, in seconds.
LEEWAY_SECONDS = 30


class TokenError(Exception):
    """The token cannot be trusted; the message says why."""


class MalformedToken(TokenError):
    """Not a compact JWT, or its parts do not decode."""


class UnknownKey(TokenError):
    """The ``kid`` is not among the keys given (the key set may need a refresh)."""


class InvalidTokenSignature(TokenError):
    """The signature does not match the key."""


class ExpiredToken(TokenError):
    """``exp`` is in the past."""


class TokenNotYetValid(TokenError):
    """``nbf`` or ``iat`` is in the future."""


class InvalidAudience(TokenError):
    """``aud`` is not one this verifier accepts."""


class InvalidIssuer(TokenError):
    """``iss`` is not PlantCraft."""


# Base64url ---------------------------------------------------------------------


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str):
        raise MalformedToken("Token part is not text.")
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise MalformedToken("Token part is not valid base64url.") from exc


# Keys --------------------------------------------------------------------------


def generate_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_key_to_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def private_key_from_pem(data: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("The key file does not hold an Ed25519 private key.")
    return key


def _public_raw(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(key: Ed25519PublicKey | Ed25519PrivateKey) -> str:
    """A stable id for a key: the first 16 characters of its JWK thumbprint (RFC 7638)."""

    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    canonical = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": b64url_encode(_public_raw(public))},
        separators=(",", ":"),
        sort_keys=True,
    )
    return b64url_encode(hashlib.sha256(canonical.encode()).digest())[:16]


def public_key_to_jwk(
    key: Ed25519PublicKey | Ed25519PrivateKey, kid: str | None = None
) -> dict[str, str]:
    """The public half as a JWK: ``{"kid", "kty": "OKP", "crv": "Ed25519", "x"}``."""

    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return {
        "kid": kid or key_id(public),
        "kty": "OKP",
        "crv": "Ed25519",
        "x": b64url_encode(_public_raw(public)),
    }


def public_key_from_jwk(jwk: Mapping[str, Any]) -> Ed25519PublicKey:
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
        raise UnknownKey("Only Ed25519 keys (kty OKP, crv Ed25519) are supported.")
    raw = b64url_decode(str(jwk.get("x", "")))
    if len(raw) != 32:
        raise UnknownKey("The Ed25519 public key must be 32 bytes.")
    return Ed25519PublicKey.from_public_bytes(raw)


def _key_set(jwks: Any) -> dict[str, Mapping[str, Any]]:
    """``{"keys": [...]}``, a list of JWKs, or ``{kid: jwk}``, as ``{kid: jwk}``."""

    if isinstance(jwks, Mapping) and "keys" in jwks:
        jwks = jwks["keys"]
    if isinstance(jwks, Mapping):
        return {str(kid): jwk for kid, jwk in jwks.items()}
    return {str(jwk.get("kid")): jwk for jwk in jwks or [] if isinstance(jwk, Mapping)}


# Tokens ------------------------------------------------------------------------


class _JsonEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        return str(o)


def encode(claims: Mapping[str, Any], private_key: Ed25519PrivateKey, kid: str) -> str:
    """A compact JWT signed with ``private_key``; ``kid`` goes in the header."""

    return pyjwt.encode(
        dict(claims),
        private_key,
        algorithm=ALGORITHM,
        headers={"kid": kid, "typ": "JWT"},
        json_encoder=_JsonEncoder,
    )


def unverified_header(token: str) -> dict[str, Any]:
    """The token's header, read without checking anything (to pick the key)."""

    if not isinstance(token, str) or token.count(".") != 2:
        raise MalformedToken("A token has three parts separated by dots.")
    try:
        return pyjwt.get_unverified_header(token)
    except pyjwt.PyJWTError as exc:
        raise MalformedToken(f"The token header does not decode: {exc}") from exc


def unverified_claims(token: str) -> dict[str, Any]:
    """The token's claims, read without checking the signature: never trust them for access."""

    unverified_header(token)
    try:
        claims = pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.PyJWTError as exc:
        raise MalformedToken(f"The token claims do not decode: {exc}") from exc
    if not isinstance(claims, dict):
        raise MalformedToken("The token claims are not a JSON object.")
    return claims


def decode(
    token: str,
    jwks: Any,
    audience: str | Iterable[str] | None,
    *,
    issuer: str | None = ISSUER,
    leeway: float = LEEWAY_SECONDS,
) -> dict[str, Any]:
    """The verified claims of ``token`` (PyJWT checks the signature and the claims).

    ``jwks`` is the key set (``{"keys": [...]}`` as served, a list, or
    ``{kid: jwk}``). ``audience`` is the id (or ids) this verifier accepts;
    ``None`` skips the audience check. ``exp`` is required; ``nbf`` and ``iat`` may not be in
    the future.
    """

    header = unverified_header(token)
    if header.get("alg") != ALGORITHM:
        raise MalformedToken(f"Unsupported algorithm {header.get('alg')!r}; expected EdDSA.")
    kid = str(header.get("kid") or "")
    jwk = _key_set(jwks).get(kid)
    if jwk is None:
        raise UnknownKey(f"Unknown signing key {kid!r}.")
    public = public_key_from_jwk(jwk)
    accepted = (
        None if audience is None else [audience] if isinstance(audience, str) else list(audience)
    )
    try:
        return pyjwt.decode(
            token,
            public,
            algorithms=[ALGORITHM],
            audience=accepted,
            issuer=issuer,
            leeway=leeway,
            options={
                "require": ["exp"],
                "verify_aud": accepted is not None,
                "verify_iss": issuer is not None,
                "verify_iat": True,
                # ``sub`` and ``jti`` are ours to read; PyJWT would refuse a number there.
                "verify_sub": False,
                "verify_jti": False,
            },
        )
    except pyjwt.InvalidSignatureError as exc:
        raise InvalidTokenSignature("The token signature is not valid.") from exc
    except pyjwt.ExpiredSignatureError as exc:
        raise ExpiredToken("The token has expired.") from exc
    except (pyjwt.ImmatureSignatureError, pyjwt.InvalidIssuedAtError) as exc:
        raise TokenNotYetValid(f"The token is not valid yet: {exc}.") from exc
    except pyjwt.InvalidAudienceError as exc:
        raise InvalidAudience("The token is meant for another audience.") from exc
    except pyjwt.InvalidIssuerError as exc:
        raise InvalidIssuer(f"The token was not issued by {issuer!r}.") from exc
    except pyjwt.MissingRequiredClaimError as exc:
        raise MalformedToken("The token has no expiry (exp).") from exc
    except pyjwt.PyJWTError as exc:
        raise MalformedToken(f"The token does not decode: {exc}") from exc


__all__ = [
    "ALGORITHM",
    "ISSUER",
    "ExpiredToken",
    "InvalidAudience",
    "InvalidIssuer",
    "InvalidTokenSignature",
    "MalformedToken",
    "TokenError",
    "TokenNotYetValid",
    "UnknownKey",
    "decode",
    "encode",
    "generate_private_key",
    "key_id",
    "private_key_from_pem",
    "private_key_to_pem",
    "public_key_from_jwk",
    "public_key_to_jwk",
    "unverified_claims",
    "unverified_header",
]
