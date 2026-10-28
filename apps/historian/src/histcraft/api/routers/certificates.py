"""The certificates the Historian holds, for PlantCraft's Health list (B17).

| Route | Answer |
|---|---|
| ``GET /api/v1/certificates`` | ``[{id, name, use, source_id?, not_after, fingerprint_sha256}]`` |
| ``POST /api/v1/certificates/{id}/renew`` | the renewed item, with ``pem`` (client only) |

``use`` is ``opcua-client`` (the Historian's own certificate, the one secure servers trust) or
``opcua-server-pinned`` (a server certificate trusted on a source; ``not_after`` is null until
the Historian has seen it once). PlantCraft reads the list with its service token, like the API
v1 reads; renewing is an administrator's change, made with their own token.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from cryptography import x509
from fastapi import APIRouter, HTTPException

from histcraft.api.deps import AdminUser, RuntimeDep
from histcraft.api.routers.reads import Reader
from histcraft.i18n import t
from histcraft.sources import certificates

router = APIRouter(prefix="/api/v1/certificates", tags=["certificates"])
CLIENT_ID = "opcua-client"


def _expiry(der: bytes | None) -> str | None:
    if der is None:
        return None
    moment = x509.load_der_x509_certificate(der).not_valid_after_utc
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _client(runtime: Any) -> dict[str, Any]:
    cert, _key = certificates.identity(runtime.settings.data_dir)
    der = cert.read_bytes()
    return {
        "id": CLIENT_ID,
        "name": t("Historian OPC UA client"),
        "use": "opcua-client",
        "not_after": _expiry(der),
        "fingerprint_sha256": certificates.thumbprint(der),
    }


@router.get("")
def listing(runtime: RuntimeDep, _reader: Reader) -> list[dict[str, Any]]:
    """The client certificate, then each source's trusted server certificate."""

    items = [_client(runtime)]
    for source in runtime.catalog.sources():
        pinned = str((source.get("options") or {}).get("server_thumbprint") or "")
        if source.get("kind") != "opcua" or not pinned:
            continue
        der = certificates.seen_server(runtime.settings.data_dir, pinned)
        items.append(
            {
                "id": f"server-{source['id']}",
                "name": t("{source}: server certificate", source=source["name"]),
                "use": "opcua-server-pinned",
                "source_id": source["id"],
                "not_after": _expiry(der),
                "fingerprint_sha256": pinned,
            }
        )
    return items


@router.post("/{certificate_id}/renew")
def renew(certificate_id: str, runtime: RuntimeDep, user: AdminUser) -> dict[str, Any]:
    """A new client certificate (two years); the item, with the certificate as PEM for the
    servers to trust. A server's certificate is renewed on the server, then trusted again."""

    if certificate_id != CLIENT_ID:
        raise HTTPException(
            404 if not certificate_id.startswith("server-") else 422,
            t("Only the Historian's own certificate is renewed here."),
        )
    cert = certificates.renew(runtime.settings.data_dir)
    item = _client(runtime)
    runtime.audit(user, "certificate.renew", CLIENT_ID, {"not_after": item["not_after"]})
    return {**item, "pem": certificates.pem(cert.read_bytes())}
