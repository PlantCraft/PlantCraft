"""Secure OPC UA (G2): Sign and SignAndEncrypt with a trusted server certificate only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from histcraft.collector.opcua import OpcUaReader
from histcraft.sources import certificates
from tests.opcua_server import PlantServer


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    plant = PlantServer(secure_dir=tmp_path_factory.mktemp("server-pki")).start()
    yield plant
    plant.stop()


def source(server, **options) -> dict:
    return {
        "endpoint": server.endpoint,
        "namespace_uri": "urn:histcraft:test",
        "options": {
            "security_mode": "SignAndEncrypt",
            "security_policy": "Basic256Sha256",
            **options,
        },
    }


async def read_once(reader: OpcUaReader) -> float:
    await reader.connect()
    try:
        readings = await reader.read(["ns=2;s=FIC-101.PV"])
        return readings["ns=2;s=FIC-101.PV"].value
    finally:
        await reader.close()


def test_an_untrusted_server_shows_its_certificate_first(server, tmp_path):
    reader = OpcUaReader(source(server), data_dir=tmp_path)
    with pytest.raises(certificates.UntrustedServer) as caught:
        asyncio.run(read_once(reader))
    assert caught.value.certificate["thumbprint"] == certificates.thumbprint(server.certificate)
    assert "Test plant" in caught.value.certificate["subject"]


@pytest.mark.parametrize("mode", ["Sign", "SignAndEncrypt"])
def test_a_trusted_server_is_read_over_a_secure_channel(server, tmp_path, mode):
    pinned = certificates.thumbprint(server.certificate)
    reader = OpcUaReader(
        source(server, security_mode=mode, server_thumbprint=pinned), data_dir=tmp_path
    )
    assert asyncio.run(read_once(reader)) == 50.0
    # Historian made its own certificate once, the key readable by its owner only.
    cert, key = certificates.identity(tmp_path)
    assert cert.is_file() and (key.stat().st_mode & 0o077) == 0


def test_another_certificate_than_the_trusted_one_is_refused(server, tmp_path):
    reader = OpcUaReader(source(server, server_thumbprint="AB:" * 31 + "CD"), data_dir=tmp_path)
    with pytest.raises(certificates.UntrustedServer, match="another certificate"):
        asyncio.run(read_once(reader))


def test_trusting_a_server_is_an_admin_change_kept_on_the_source(client, runtime):
    from histcraft.catalog.models import SourceIn

    runtime.catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://127.0.0.1:4840/"), create=True
    )
    pinned = "AB:" * 31 + "CD"
    answer = client.post("/hist/api/sources/plant/trust", json={"thumbprint": pinned.lower()})
    assert answer.status_code == 200
    assert answer.json()["options"]["server_thumbprint"] == pinned
    assert client.post("/hist/api/sources/plant/trust", json={"thumbprint": "x"}).status_code == 422
    certificate = client.get("/hist/api/opcua/certificate")
    assert certificate.status_code == 200 and certificate.content[:1] == b"\x30"


def test_the_certificates_are_listed_with_their_expiry_and_the_client_one_renewed(
    server, client, runtime
):
    from histcraft.catalog.models import SourceIn

    pinned = certificates.thumbprint(server.certificate)
    runtime.catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint=server.endpoint), create=True
    )
    client.post("/hist/api/sources/plant/trust", json={"thumbprint": pinned})
    listed = client.get("/hist/api/v1/certificates").json()
    own, trusted = listed
    assert (own["id"], own["use"]) == ("opcua-client", "opcua-client")
    days = (datetime.fromisoformat(own["not_after"]) - datetime.now(UTC)).days
    assert 700 <= days <= 731
    # A pinned server's expiry is known once the Historian has seen its certificate.
    assert trusted == {
        "id": "server-plant",
        "name": "Plant: server certificate",
        "use": "opcua-server-pinned",
        "source_id": "plant",
        "not_after": None,
        "fingerprint_sha256": pinned,
    }
    certificates.remember_server(runtime.settings.data_dir, server.certificate)
    assert client.get("/hist/api/v1/certificates").json()[1]["not_after"]

    renewed = client.post("/hist/api/v1/certificates/opcua-client/renew").json()
    assert renewed["fingerprint_sha256"] != own["fingerprint_sha256"]
    assert renewed["pem"].startswith("-----BEGIN CERTIFICATE-----")
    assert client.get("/hist/api/v1/certificates").json()[0] == {
        key: value for key, value in renewed.items() if key != "pem"
    }
    assert client.post("/hist/api/v1/certificates/server-plant/renew").status_code == 422
