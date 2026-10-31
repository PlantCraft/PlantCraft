"""The key pair PlantCraft signs its tokens with (Ed25519 JWT, API v1).

The private key is generated on first start and kept beside the database
(``tokens.key``, mode 0600), or at ``PLANTCRAFT_TOKEN_KEY_FILE``. Rotating
moves the current public key to ``tokens.retired.json``: it stays listed at
``/api/v1/auth/keys`` so tokens already issued keep verifying until they expire.
Apps verify offline with the public keys; the private key never leaves this folder.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from plantcraft_sdk import jwt
from plantcraft_sdk.contract import CENTRAL_AUDIENCE, ISSUER

VERIFIED_CACHE_SIZE = 4096

LOGGER = logging.getLogger(__name__)
# Retired public keys kept listed (newest first). Tokens live at most an hour,
# so a key retired twice ago is long unused; a few are kept for safety.
RETIRED_KEPT = 5


def key_file_for(database_path: str | Path) -> Path:
    configured = os.environ.get("PLANTCRAFT_TOKEN_KEY_FILE", "").strip()
    return Path(configured) if configured else Path(database_path).with_name("tokens.key")


def _write_private(path: Path, data: bytes, *, exclusive: bool) -> bool:
    """Write ``data`` readable by this user only; False when the file already exists."""

    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "wb") as file:
        file.write(data)
    os.chmod(path, 0o600)
    return True


class KeyRing:
    """Signs and verifies PlantCraft tokens; lists the public keys for the apps."""

    def __init__(self, key_file: str | Path):
        self.key_file = Path(key_file)
        self.retired_file = self.key_file.with_name(self.key_file.stem + ".retired.json")
        self._lock = threading.Lock()
        self._signature: tuple[float, float] | None = None
        self._private = None
        self.kid = ""
        self._retired: list[dict[str, str]] = []
        # (token, audience) -> (claims, exp, kid): tokens already verified, until they expire
        # (the signature check cost about 0.2 ms on every request of an app).
        self._verified: dict[tuple[str, str], tuple[dict[str, Any], float, str]] = {}
        self._load()

    @classmethod
    def for_database(cls, database_path: str | Path) -> KeyRing:
        return cls(key_file_for(database_path))

    # Files ------------------------------------------------------------------

    def _mtimes(self) -> tuple[float, float]:
        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        return mtime(self.key_file), mtime(self.retired_file)

    def _load(self) -> None:
        """Read the key files, creating the key pair on first start."""

        with self._lock:
            try:
                self.key_file.parent.mkdir(parents=True, exist_ok=True)
                if not self.key_file.exists():
                    # Exclusive create: two workers starting together end up with one key.
                    key = jwt.generate_private_key()
                    _write_private(self.key_file, jwt.private_key_to_pem(key), exclusive=True)
                private = jwt.private_key_from_pem(self.key_file.read_bytes())
            except OSError as exc:
                if self._private is not None:
                    return
                # Read-only storage: tokens stay valid until the next restart.
                LOGGER.warning("Token key not stored (%s); using a key for this run only.", exc)
                private = jwt.generate_private_key()
            try:
                retired = json.loads(self.retired_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                retired = []
            self._private = private
            self.kid = jwt.key_id(private)
            self._retired = [item for item in retired if isinstance(item, dict)][:RETIRED_KEPT]
            self._signature = self._mtimes()

    def _fresh(self) -> None:
        # Another worker may have rotated the key: follow the files.
        if self._signature != self._mtimes():
            self._load()

    # Keys -------------------------------------------------------------------

    def jwks(self) -> dict[str, list[dict[str, str]]]:
        """The current public key first, then the retired ones still accepted."""

        self._fresh()
        current = jwt.public_key_to_jwk(self._private, self.kid)
        return {"keys": [current, *(item for item in self._retired if item["kid"] != self.kid)]}

    def rotate(self) -> str:
        """Sign with a new key from now on; the old public key stays listed. Returns the new kid."""

        self._fresh()
        with self._lock:
            retired = [jwt.public_key_to_jwk(self._private, self.kid), *self._retired]
            key = jwt.generate_private_key()
            _write_private(
                self.retired_file,
                json.dumps(retired[:RETIRED_KEPT], indent=2).encode(),
                exclusive=False,
            )
            _write_private(self.key_file, jwt.private_key_to_pem(key), exclusive=False)
        self._load()
        return self.kid

    # Tokens -----------------------------------------------------------------

    def issue(
        self,
        subject: str,
        *,
        ttl: int,
        audience: str = CENTRAL_AUDIENCE,
        not_before: int = 0,
        **claims: Any,
    ) -> tuple[str, int]:
        """A signed token for ``subject`` and its expiry (Unix seconds).

        ``iat`` is never earlier than ``not_before`` (the subject's last revocation), so a token
        issued in the second of a revocation still counts as issued after it.
        """

        self._fresh()
        issued = max(int(time.time()), int(not_before))
        expires = issued + int(ttl)
        body = {
            "iss": ISSUER,
            "sub": subject,
            **claims,
            "aud": audience,
            "iat": issued,
            "exp": expires,
        }
        return jwt.encode(body, self._private, self.kid), expires

    def verify(self, token: str, audience: str = CENTRAL_AUDIENCE) -> dict[str, Any]:
        """The token's claims; raises ``plantcraft_sdk.jwt.TokenError``."""

        keys = self.jwks()
        hit = self._verified.get((token, audience))
        if hit is not None:
            claims, expires, kid = hit
            if time.time() <= expires + jwt.LEEWAY_SECONDS and kid in jwt.key_ids(keys):
                return dict(claims)
            self._verified.pop((token, audience), None)
        claims = jwt.decode(token, keys, audience)
        if len(self._verified) >= VERIFIED_CACHE_SIZE:
            try:
                self._verified.pop(next(iter(self._verified)))
            except (StopIteration, KeyError, RuntimeError):
                pass
        kid = str(jwt.unverified_header(token).get("kid") or "")
        self._verified[(token, audience)] = (dict(claims), float(claims.get("exp") or 0), kid)
        return claims
