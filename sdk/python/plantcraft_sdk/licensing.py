"""Licences of closed apps: a ``.pclicense`` file the app's publisher signs (docs/app-package.md §8).

A licence says which app, for which customer and which installation, until when, and with which
limits. Its publisher signs it with the same Ed25519 key that signs the app's packages, so the
check needs no internet and no server of PlantCraft or of the publisher::

    # The publisher, once per customer (the key never leaves the publisher):
    plantcraft-app license issue --key keys/acme.key --app pidcraft --publisher "Acme Tools" \\
        --customer "Refinery North" --installation 6f1c... --expires 2027-12-31 \\
        --limit sheets=200 --out refinery-north.pclicense

    # The app, at start and every hour (plantcraft_sdk.licensing.LicenseGuard):
    guard = LicenseGuard(app_id="pidcraft", public_key=PUBLISHER_KEY, grace_days=14)
    state = guard.check(raw_license_bytes, installation_id)
    state.usable, state.status, state.days_left

The file is JSON: ``{"format": 1, "license": {...}, "signature": "<base64>"}``; the signature
covers the licence's canonical JSON (sorted keys, no spaces). The app keeps its publisher's
public key inside its own (compiled) code, so a changed PlantCraft cannot hand it a forged
licence. PlantCraft checks the same signature against its trusted publishers when an
administrator adds the file (Apps › Licences), and serves it to the app it is for.

What a licence is worth, plainly: it keeps an honest customer inside what they bought and makes a
copied install fail loudly. Someone who can change the app's code can remove the check; compiling
the app (Nuitka) makes that real work, not impossible. The contract is the real protection.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

FORMAT = 1
LIMIT_BYTES = 16 * 1024
FIELDS = {
    "id",
    "app",
    "publisher",
    "customer",
    "installation",
    "issued",
    "expires",
    "limits",
    "features",
}
REQUIRED = {"id", "app", "publisher", "customer", "installation", "issued", "expires"}
# "*": any installation (a trial or a site licence the publisher chooses to give).
ANY_INSTALLATION = "*"
APP_ID = re.compile(r"^[a-z][a-z0-9]{2,30}$")
WORD = re.compile(r"^[a-z][a-z0-9_.-]{0,40}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTALLATION = re.compile(r"^(\*|[0-9A-Za-z][0-9A-Za-z-]{7,63})$")
STATUSES = ("valid", "grace", "expired", "missing", "invalid")


class LicenseError(ValueError):
    """The licence file cannot be trusted or is not for this app or installation."""


def canonical(document: Any) -> bytes:
    """The bytes a licence's signature covers."""

    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_public_key(data: bytes | str) -> Ed25519PublicKey:
    """A publisher's public key from its ``.pub`` file (PEM)."""

    raw = data.encode() if isinstance(data, str) else data
    try:
        key = serialization.load_pem_public_key(raw)
    except ValueError as exc:
        raise LicenseError("not a PEM public key") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise LicenseError("the publisher key must be Ed25519")
    return key


def _day(value: Any, what: str) -> date:
    if not isinstance(value, str) or not DAY.match(value):
        raise LicenseError(f"{what}: a day like 2027-12-31")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise LicenseError(f"{what}: not a real day") from exc


def validate(body: Any) -> dict[str, Any]:
    """The licence's fields, checked one by one; raises LicenseError."""

    if not isinstance(body, dict):
        raise LicenseError("license: a JSON object")
    unknown = set(body) - FIELDS
    if unknown:
        raise LicenseError(f"license: unknown fields {sorted(unknown)}")
    missing = REQUIRED - set(body)
    if missing:
        raise LicenseError(f"license: missing {sorted(missing)}")
    for name in ("id", "publisher", "customer"):
        value = body[name]
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 120
            or any(ord(char) < 32 for char in value)
        ):
            raise LicenseError(f"license.{name}: 1 to 120 characters of text")
    if not isinstance(body["app"], str) or not APP_ID.match(body["app"]):
        raise LicenseError("license.app: an app id")
    if not isinstance(body["installation"], str) or not INSTALLATION.match(body["installation"]):
        raise LicenseError('license.installation: the installation id, or "*" for any')
    issued, expires = (
        _day(body["issued"], "license.issued"),
        _day(body["expires"], "license.expires"),
    )
    if expires < issued:
        raise LicenseError("license.expires is before license.issued")
    limits = body.get("limits", {})
    if not isinstance(limits, dict) or len(limits) > 30:
        raise LicenseError("license.limits: a table of at most 30 name = number")
    for name, value in limits.items():
        if (
            not WORD.match(name)
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise LicenseError("license.limits: lower-case names and whole numbers")
    features = body.get("features", [])
    if not isinstance(features, list) or len(features) > 50:
        raise LicenseError("license.features: a list of at most 50 names")
    if any(not isinstance(item, str) or not WORD.match(item) for item in features):
        raise LicenseError("license.features: lower-case names")
    return {**body, "limits": dict(limits), "features": list(features)}


def issue(key: Ed25519PrivateKey, body: dict[str, Any]) -> bytes:
    """A signed licence file (the bytes of a ``.pclicense``)."""

    clean = validate(body)
    signature = base64.b64encode(key.sign(canonical(clean))).decode()
    document = {"format": FORMAT, "license": clean, "signature": signature}
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def read(data: bytes, keys: dict[str, Ed25519PublicKey] | Ed25519PublicKey) -> dict[str, Any]:
    """The licence of a ``.pclicense`` whose signature holds; raises LicenseError.

    ``keys``: the publisher's public key, or the trusted publishers by key file name
    (``acme-tools`` for ``acme-tools.pub``), the licence's ``publisher`` choosing one.
    """

    if len(data) > LIMIT_BYTES:
        raise LicenseError("the licence file is too large")
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseError("the licence file is not JSON") from exc
    if not isinstance(document, dict) or set(document) != {"format", "license", "signature"}:
        raise LicenseError('a licence file holds "format", "license" and "signature"')
    if document["format"] != FORMAT:
        raise LicenseError(f"licence format must be {FORMAT}")
    body = validate(document["license"])
    if isinstance(keys, Ed25519PublicKey):
        key = keys
    else:
        key = keys.get(publisher_file(body["publisher"]))
        if key is None:
            raise LicenseError(f"unknown publisher {body['publisher']!r}")
    try:
        signature = base64.b64decode(str(document["signature"]), validate=True)
        key.verify(signature, canonical(body))
    except (binascii.Error, ValueError, InvalidSignature) as exc:
        raise LicenseError("the licence's signature does not hold") from exc
    return body


def publisher_file(name: str) -> str:
    """The trusted key's file name (without ``.pub``) of a publisher, as packages use it."""

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return {"plantcraft": "processcraft"}.get(slug, slug)


@dataclass(frozen=True)
class LicenseState:
    """What an app may do under its licence now."""

    status: str  # valid | grace | expired | missing | invalid
    message: str
    license: dict[str, Any] = field(default_factory=dict)
    days_left: int | None = None

    @property
    def usable(self) -> bool:
        """valid, or expired less than ``grace_days`` ago: the app works and warns."""

        return self.status in ("valid", "grace")

    def limit(self, name: str, default: int | None = None) -> int | None:
        return self.license.get("limits", {}).get(name, default)

    def has(self, feature: str) -> bool:
        return feature in self.license.get("features", [])

    def to_json(self) -> dict[str, Any]:
        body = self.license
        return {
            "status": self.status,
            "usable": self.usable,
            "message": self.message,
            "days_left": self.days_left,
            "customer": body.get("customer"),
            "expires": body.get("expires"),
            "limits": body.get("limits", {}),
            "features": body.get("features", []),
            "id": body.get("id"),
        }


def state(
    data: bytes | None,
    key: Ed25519PublicKey,
    *,
    app_id: str,
    installation: str | None,
    grace_days: int = 14,
    now: datetime | None = None,
) -> LicenseState:
    """The licence's state for this app on this installation (never raises)."""

    if not data:
        return LicenseState("missing", "No licence: an administrator adds it in Apps › Licences.")
    try:
        body = read(data, key)
    except LicenseError as exc:
        return LicenseState("invalid", f"The licence cannot be used: {exc}.")
    if body["app"] != app_id:
        return LicenseState("invalid", f"The licence is for {body['app']}, not {app_id}.")
    if body["installation"] != ANY_INSTALLATION and body["installation"] != installation:
        return LicenseState(
            "invalid", "The licence is for another installation (its installation id differs)."
        )
    today = (now or datetime.now(UTC)).astimezone(UTC).date()
    expires = date.fromisoformat(body["expires"])
    left = (expires - today).days
    if left >= 0:
        return LicenseState(
            "valid", f"Licensed to {body['customer']} until {body['expires']}.", body, left
        )
    if today <= expires + timedelta(days=grace_days):
        return LicenseState(
            "grace",
            f"The licence ended on {body['expires']}; the app keeps working "
            f"{grace_days + left} more days. Ask its publisher for a new one.",
            body,
            left,
        )
    return LicenseState("expired", f"The licence ended on {body['expires']}.", body, left)


class LicenseGuard:
    """An app's licence check: reads the licence PlantCraft keeps for it and caches the state.

    ``fetch()`` returns the licence's bytes (``SuiteClient.app_license()``) or None; the app
    calls ``refresh()`` at start and on a schedule, and ``current`` everywhere else.
    """

    def __init__(
        self, *, app_id: str, public_key: Ed25519PublicKey | bytes | str, grace_days: int = 14
    ) -> None:
        self.app_id = app_id
        self.key = (
            public_key if isinstance(public_key, Ed25519PublicKey) else load_public_key(public_key)
        )
        self.grace_days = grace_days
        self.current = LicenseState("missing", "The licence has not been read yet.")

    def check(
        self, data: bytes | None, installation: str | None, now: datetime | None = None
    ) -> LicenseState:
        self.current = state(
            data,
            self.key,
            app_id=self.app_id,
            installation=installation,
            grace_days=self.grace_days,
            now=now,
        )
        return self.current

    def refresh(self, client: Any) -> LicenseState:
        """Reads the licence through the API v1 client (``app_license``, ``installation_id``)."""

        try:
            data = client.app_license()
            installation = client.installation_id()
        except Exception as exc:  # noqa: BLE001 - PlantCraft away: keep the last state
            if self.current.status in ("valid", "grace"):
                return self.current
            return LicenseState(
                "missing", f"PlantCraft could not be asked for the licence ({exc})."
            )
        return self.check(data, installation)


def new_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


__all__ = [
    "ANY_INSTALLATION",
    "LicenseError",
    "LicenseGuard",
    "LicenseState",
    "issue",
    "load_public_key",
    "publisher_file",
    "read",
    "state",
    "validate",
]
