"""Secure OPC UA (G2): the Historian's client certificate and the server certificates it trusts.

A secure channel (Sign or SignAndEncrypt) needs a certificate on each side. Historian makes its
own once, self-signed for two years, in ``<data folder>/pki/`` (the key readable by its owner
only): an administrator downloads it from the Sources page and adds it to the server's trusted
list. The server's certificate is trusted by its SHA-256 thumbprint, pinned on the source after
an administrator checked it (Test shows it): a server presenting another certificate is refused.

PlantCraft's Health lists both kinds with their expiry (``GET /api/v1/certificates``, B17); the
client certificate is renewed from there. Each server certificate seen is kept in
``pki/servers/`` so its expiry is known (the source keeps only the thumbprint).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from asyncua import Client, ua
from asyncua.crypto import security_policies
from asyncua.crypto.cert_gen import (
    dump_private_key_as_pem,
    generate_private_key,
    generate_self_signed_app_certificate,
)
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtendedKeyUsageOID
from plantcraft_sdk.files import write_atomic

from histcraft.i18n import t

# The application URI in the certificate: the client must present the same one.
APP_URI = "urn:processcraft:histcraft"
HOST_NAME = "histcraft"
# Two years: an expiry close enough that renewing is a habit, listed on PlantCraft's Health.
CERT_DAYS = 730
MODES = ("None", "Sign", "SignAndEncrypt")
POLICIES: dict[str, Any] = {
    "Basic256Sha256": security_policies.SecurityPolicyBasic256Sha256,
    "Aes128_Sha256_RsaOaep": security_policies.SecurityPolicyAes128Sha256RsaOaep,
    "Aes256_Sha256_RsaPss": security_policies.SecurityPolicyAes256Sha256RsaPss,
}
DEFAULT_POLICY = "Basic256Sha256"


def pki_folder(data_dir: Path) -> Path:
    return Path(data_dir) / "pki"


def _new_identity() -> tuple[bytes, bytes]:
    """``(certificate DER, key PEM)`` freshly made."""

    key = generate_private_key()
    cert = generate_self_signed_app_certificate(
        key,
        APP_URI,
        {"commonName": "PlantCraft Historian", "organizationName": "PlantCraft"},
        [x509.UniformResourceIdentifier(APP_URI), x509.DNSName(HOST_NAME)],
        extended=[ExtendedKeyUsageOID.CLIENT_AUTH],
        days=CERT_DAYS,
    )
    return cert.public_bytes(Encoding.DER), dump_private_key_as_pem(key)


def identity(data_dir: Path) -> tuple[Path, Path]:
    """``(certificate DER, key PEM)`` of the Historian, made on first use.

    The server and the collector share the data folder: each writes to a temporary file and
    renames it, so a reader never sees half a file, and the first one written wins.
    """

    folder = pki_folder(data_dir)
    cert_path, key_path = folder / "histcraft-client.der", folder / "histcraft-client.key.pem"
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path
    folder.mkdir(parents=True, exist_ok=True)
    cert, key = _new_identity()
    _publish(key_path, key, mode=0o600)
    _publish(cert_path, cert, mode=0o644)
    return cert_path, key_path


def renew(data_dir: Path) -> Path:
    """A new client certificate and key in place of the old ones; the certificate's path.

    Sessions already open keep the old pair; the next connection presents the new one, which
    each secure server must trust first (download it and add it to the server's list).
    """

    cert_path, key_path = identity(data_dir)
    cert, key = _new_identity()
    for path, data, mode in ((key_path, key, 0o600), (cert_path, cert, 0o644)):
        write_atomic(path, data, mode=mode)
    return cert_path


def remember_server(data_dir: Path | None, der: bytes) -> None:
    """Keep a server certificate seen, by its thumbprint, so its expiry can be listed."""

    if data_dir is None:
        return
    folder = pki_folder(data_dir) / "servers"
    folder.mkdir(parents=True, exist_ok=True)
    _publish(folder / f"{thumbprint(der).replace(':', '')}.der", der, mode=0o644)


def seen_server(data_dir: Path, pinned: str) -> bytes | None:
    """The server certificate kept for a thumbprint, if one was seen."""

    path = pki_folder(data_dir) / "servers" / f"{pinned.replace(':', '')}.der"
    return path.read_bytes() if path.is_file() else None


def pem(der: bytes) -> str:
    return x509.load_der_x509_certificate(der).public_bytes(Encoding.PEM).decode()


def _publish(path: Path, data: bytes, *, mode: int) -> None:
    if path.exists():
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    try:
        os.link(temporary, path)  # fails when another process published first: theirs wins
    except FileExistsError:
        pass
    finally:
        temporary.unlink(missing_ok=True)


def server_certificate(der: bytes) -> bytes:
    """The server's own certificate out of an endpoint's chain (the first DER element)."""

    if len(der) < 4:
        return der
    length = int.from_bytes(der[2:4], "big") + 4
    return der[:length]


def thumbprint(der: bytes) -> str:
    """SHA-256 of a certificate, as uppercase hex pairs (``AB:CD:...``), the form tools show."""

    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def describe(der: bytes) -> dict[str, Any]:
    """What a person checks before trusting a certificate."""

    cert = x509.load_der_x509_certificate(der)
    return {
        "thumbprint": thumbprint(der),
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
    }


class UntrustedServer(Exception):
    """A secure source whose server certificate is not (or no longer) the one trusted."""

    def __init__(self, certificate: dict[str, Any], message: str = ""):
        super().__init__(
            message
            or t(
                "Check the server certificate {print} and trust it on the source.",
                print=certificate["thumbprint"],
            )
        )
        self.certificate = certificate


async def secure(
    client: Client, endpoint: str, options: dict[str, Any], data_dir: Path | None, timeout: float
) -> None:
    """Sign or SignAndEncrypt on ``client`` before it connects; nothing for mode None.

    The server's certificate comes from GetEndpoints over an unsecured channel (the discovery
    every OPC UA client makes first) and must match the thumbprint trusted on the source.
    """

    mode = str(options.get("security_mode") or "None")
    if mode == "None":
        return
    name = str(options.get("security_policy") or DEFAULT_POLICY)
    policy = POLICIES.get(name)
    if policy is None:
        raise ValueError(t("Unknown security policy {name}.", name=name))
    endpoints = await Client(url=endpoint, timeout=timeout).connect_and_get_server_endpoints()
    wanted = ua.MessageSecurityMode[mode]
    found = next(
        (
            item
            for item in endpoints
            if item.SecurityMode == wanted and item.SecurityPolicyUri == policy.URI
        ),
        None,
    )
    if found is None:
        raise ValueError(
            t("The server offers no {mode} endpoint with {policy}.", mode=mode, policy=name)
        )
    der = server_certificate(found.ServerCertificate)
    remember_server(data_dir, der)
    pinned = str(options.get("server_thumbprint") or "")
    if not pinned:
        raise UntrustedServer(describe(der))
    if thumbprint(der) != pinned:
        raise UntrustedServer(
            describe(der), t("The server presents another certificate than the one trusted.")
        )
    if data_dir is None:
        raise ValueError(t("No data folder for the Historian's certificate."))
    cert, key = identity(data_dir)
    client.application_uri = APP_URI
    await client.set_security(policy, str(cert), str(key), server_certificate=der, mode=wanted)
