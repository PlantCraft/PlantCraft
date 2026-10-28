"""Ed25519 tokens: round trip and every way a token is refused."""

from __future__ import annotations

import time

import pytest

from plantcraft_sdk import jwt


@pytest.fixture()
def key():
    return jwt.generate_private_key()


def _claims(**extra):
    now = int(time.time())
    return {
        "iss": "processcraft",
        "sub": "ana",
        "aud": "linkcraft",
        "iat": now,
        "exp": now + 60,
        **extra,
    }


def test_round_trip_with_the_published_key_set(key):
    kid = jwt.key_id(key)
    token = jwt.encode(_claims(apps={"linkcraft": "editor"}), key, kid)
    keys = {"keys": [jwt.public_key_to_jwk(key, kid)]}
    claims = jwt.decode(token, keys, "linkcraft")
    assert claims["sub"] == "ana" and claims["apps"] == {"linkcraft": "editor"}
    assert jwt.unverified_header(token) == {"alg": "EdDSA", "typ": "JWT", "kid": kid}
    # Also a list of JWKs, a {kid: jwk} map and a set of audiences.
    assert jwt.decode(token, keys["keys"], {"x", "linkcraft"})["sub"] == "ana"
    assert jwt.decode(token, {kid: keys["keys"][0]}, None)["sub"] == "ana"


def test_jwk_round_trip_and_stable_key_id(key):
    jwk = jwt.public_key_to_jwk(key)
    assert jwk["kty"] == "OKP" and jwk["crv"] == "Ed25519" and jwk["kid"] == jwt.key_id(key)
    public = jwt.public_key_from_jwk(jwk)
    assert jwt.key_id(public) == jwk["kid"]
    pem = jwt.private_key_to_pem(key)
    assert jwt.key_id(jwt.private_key_from_pem(pem)) == jwk["kid"]


@pytest.mark.parametrize(
    ("claims", "audience", "error"),
    [
        ({"exp": int(time.time()) - 120}, "linkcraft", jwt.ExpiredToken),
        ({}, "dashcraft", jwt.InvalidAudience),
        ({"iss": "someone-else"}, "linkcraft", jwt.InvalidIssuer),
        ({"nbf": int(time.time()) + 600}, "linkcraft", jwt.TokenNotYetValid),
        ({"exp": None}, "linkcraft", jwt.MalformedToken),
        ({"aud": 7}, "linkcraft", jwt.InvalidAudience),
    ],
)
def test_claims_are_checked(key, claims, audience, error):
    token = jwt.encode(_claims(**claims), key, "k1")
    with pytest.raises(error):
        jwt.decode(token, [jwt.public_key_to_jwk(key, "k1")], audience)


def test_unknown_kid_wrong_key_and_tampering_are_refused(key):
    token = jwt.encode(_claims(), key, "k1")
    with pytest.raises(jwt.UnknownKey):
        jwt.decode(token, [jwt.public_key_to_jwk(key, "k2")], "linkcraft")
    other = jwt.generate_private_key()
    with pytest.raises(jwt.InvalidTokenSignature):
        jwt.decode(token, [jwt.public_key_to_jwk(other, "k1")], "linkcraft")
    head, body, signature = token.split(".")
    forged = jwt.b64url_encode(b'{"sub":"admin","exp":9999999999,"aud":"linkcraft"}')
    with pytest.raises(jwt.InvalidTokenSignature):
        jwt.decode(f"{head}.{forged}.{signature}", [jwt.public_key_to_jwk(key, "k1")], "linkcraft")


@pytest.mark.parametrize("token", ["", "a.b", "a.b.c.d", "!!!.???.***", None, 12])
def test_malformed_tokens_raise_token_errors(token):
    with pytest.raises(jwt.TokenError):
        jwt.decode(token, [], "linkcraft")


def test_other_algorithms_are_refused(key):
    head = jwt.b64url_encode(b'{"alg":"none","kid":"k1"}')
    body = jwt.b64url_encode(b'{"exp":9999999999}')
    with pytest.raises(jwt.MalformedToken):
        jwt.decode(f"{head}.{body}.", [jwt.public_key_to_jwk(key, "k1")], None)
