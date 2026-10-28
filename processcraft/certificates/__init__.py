"""The suite's certificates and when they expire (Health › Certificates; owner, 2026-10-25, B17).

Two places use one: the suite's HTTPS (``certs/cert.pem``, the client's certificate, mounted
read-only into PlantCraft at ``/certs``, where ``key.pem`` is the proxy's alone; without it the proxy's local certificate authority issues and renews
its own) and the Historian's secure OPC UA connections (its client certificate, and the servers'
certificates it pinned), which the Historian lists at ``GET /api/v1/certificates``. A certificate
that expires stops a connection without a word on any screen: the suite watch tells the
administrators 30 days before (``processcraft.watch``).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plantcraft_sdk.utc import parse_instant

WARN_DAYS = 30
# Where install.sh's certs/ folder is mounted in PlantCraft's container (read-only).
CERTS_DIR = "/certs"


def certs_dir() -> Path:
    return Path(os.environ.get("PLANTCRAFT_CERTS_DIR") or CERTS_DIR)


def _name(subject: Any) -> str:
    from cryptography.x509.oid import NameOID

    found = subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(found[0].value) if found else subject.rfc4514_string()


def describe_pem(data: bytes) -> dict[str, Any]:
    """The first certificate of a PEM file: subject, issuer, validity and SHA-256 fingerprint.
    Raises ValueError when it holds none."""

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    certificate = x509.load_pem_x509_certificate(data)
    return {
        "subject": _name(certificate.subject),
        "issuer": _name(certificate.issuer),
        "not_before": certificate.not_valid_before_utc.isoformat(),
        "not_after": certificate.not_valid_after_utc.isoformat(),
        "fingerprint_sha256": certificate.fingerprint(hashes.SHA256()).hex(),
    }


def suite_https(folder: Path | None = None) -> dict[str, Any]:
    """The suite's HTTPS certificate: the client's (``certs/cert.pem``) or the local authority's."""

    path = (folder or certs_dir()) / "cert.pem"
    item: dict[str, Any] = {"id": "https", "name": "HTTPS", "use": "https", "app": "processcraft"}
    try:
        data = path.read_bytes()
    except OSError:
        # The proxy's own certificate authority: its certificates renew by themselves.
        return {**item, "use": "https-local", "not_after": None}
    try:
        return {**item, **describe_pem(data)}
    except ValueError:
        return {**item, "not_after": None, "error": "certs/cert.pem is not a PEM certificate"}


def days_left(item: dict[str, Any], now: datetime | None = None) -> float | None:
    """Days until ``not_after`` (negative once expired); None when it has no end date."""

    end = parse_instant(item.get("not_after"))
    if end is None:
        return None
    return (end - (now or datetime.now(timezone.utc))).total_seconds() / 86400


def with_state(items: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    """Each certificate with ``days_left`` and ``state``: ok, expiring (under 30 days), expired,
    auto (renews by itself) or unknown."""

    found = []
    for item in items:
        left = days_left(item, now)
        if left is None:
            state = "auto" if item.get("use") == "https-local" else "unknown"
        elif left < 0:
            state = "expired"
        elif left < WARN_DAYS:
            state = "expiring"
        else:
            state = "ok"
        found.append(
            {**item, "days_left": None if left is None else round(left, 1), "state": state}
        )
    return found
