"""The suite's certificates (Health › Certificates, B17): read, given a state, told 30 days before."""
# ruff: noqa: F811 (the fixture "world" of tests/test_apps_api.py, imported to share it)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from processcraft.certificates import describe_pem, suite_https, with_state
from tests.test_apps_api import sign_in
from tests.test_apps_api import world as api_world  # noqa: F401
from tests.test_watch import NOW, World


def _pem(days: float, name: str = "plant.example") -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(NOW + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


def test_the_https_certificate_is_read_from_the_certs_folder(tmp_path):
    assert suite_https(tmp_path)["use"] == "https-local"
    (tmp_path / "cert.pem").write_bytes(_pem(90))
    item = suite_https(tmp_path)
    assert item["use"] == "https" and item["subject"] == "plant.example"
    assert item["not_after"].startswith((NOW + timedelta(days=90)).date().isoformat())
    assert len(item["fingerprint_sha256"]) == 64
    (tmp_path / "cert.pem").write_text("not a certificate")
    assert suite_https(tmp_path)["error"]
    with pytest.raises(ValueError):
        describe_pem(b"nothing")


def test_states_by_days_left():
    def at(days):
        return {"id": str(days), "not_after": (NOW + timedelta(days=days)).isoformat()}

    items = [at(400), at(29), at(-1), {"id": "auto", "use": "https-local", "not_after": None},
             {"id": "x", "not_after": "garbage"}]  # fmt: skip
    states = [item["state"] for item in with_state(items, NOW)]
    assert states == ["ok", "expiring", "expired", "auto", "unknown"]
    assert with_state([at(10)], NOW)[0]["days_left"] == 10.0


def test_the_watch_tells_thirty_days_before_and_reminds_a_week_before(tmp_path):
    world = World(tmp_path)
    end = {"value": NOW + timedelta(days=40)}
    items = lambda: [{"id": "opcua-client", "name": "Historian OPC UA client",  # noqa: E731
                      "use": "opcua-client", "not_after": end["value"].isoformat()}]  # fmt: skip
    world.watch.certificates = items
    assert world.ticks(3) == []
    end["value"] = NOW + timedelta(days=20)
    world.watch.forget_certificates()
    posted = world.ticks(2)
    assert len(posted) == 1 and "Historian OPC UA client" in posted[0] and "20 days" in posted[0]
    assert world.ticks(3) == []  # told once
    end["value"] = NOW + timedelta(days=5)
    world.watch.forget_certificates()
    reminder = world.ticks(1)
    assert len(reminder) == 1 and "5 days" in reminder[0]
    world.watch.forget_certificates()
    assert world.ticks(3) == []  # reminded once
    end["value"] = NOW + timedelta(days=730)
    world.watch.forget_certificates()
    back = world.ticks(1)
    assert len(back) == 1 and world.watch.overview()["open"] == []
    assert world.watch.overview()["certificates"][0]["state"] == "ok"


def test_a_broken_certificate_reader_keeps_the_last_list(tmp_path):
    world = World(tmp_path)
    calls = {"n": 0}

    def items():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("historian away")
        return [{"id": "a", "name": "A", "not_after": (NOW + timedelta(days=99)).isoformat()}]

    world.watch.certificates = items
    world.ticks(1)
    world.watch.forget_certificates()
    world.ticks(1)
    assert [item["id"] for item in world.watch.certificate_list()] == ["a"]


def test_health_lists_the_certificates_and_renew_needs_a_historian(api_world):
    client = sign_in(api_world.client())
    body = client.get("/api/operations/health").json()
    assert body["certificates"][0]["id"] == "https"
    assert client.post("/api/operations/certificates/opcua-client/renew").status_code == 404
    viewer = sign_in(api_world.client(), "eng", "password-123")
    assert viewer.post("/api/operations/certificates/opcua-client/renew").status_code == 403


def test_dates_are_utc():
    assert with_state([{"id": "n", "not_after": "2026-11-01T00:00:00"}],
                      datetime(2026, 10, 31, tzinfo=timezone.utc))[0]["days_left"] == 1.0  # fmt: skip


def test_renew_asks_the_historian_with_the_admins_own_token(api_world, monkeypatch):
    client = sign_in(api_world.client())
    rt = client.app.state.runtime
    asked = {}

    def renew(certificate_id, token):
        asked.update(id=certificate_id, claims=rt.tokens.verify(token))
        return {"id": certificate_id, "not_after": "2028-10-25T00:00:00+00:00", "pem": "PEM"}

    monkeypatch.setattr(rt.datalayer, "renew_certificate", renew)
    answer = client.post("/api/operations/certificates/opcua-client/renew").json()
    assert answer["pem"] == "PEM" and asked["id"] == "opcua-client"
    assert asked["claims"]["sub"] == "root"
