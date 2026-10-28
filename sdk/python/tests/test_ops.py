"""The operations base every server shares: JSON logs, request ids, metrics, schema stamps."""

import json
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from plantcraft_sdk.events import MAX_CONDITIONS, Condition
from plantcraft_sdk.server import logs, ops
from plantcraft_sdk.server.files import AppFiles
from plantcraft_sdk.server.queue import QueueNow
from plantcraft_sdk.server.store import Database, SchemaTooNew, schema_stamp, stamp_version
from plantcraft_sdk.server.web import mount, suite_api
from plantcraft_sdk.testing import FakePlantCraft

SECRETS = (
    "hunter2-password",
    "s3cr3t-token-value",
    "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiJhZG1pbiJ9.c2lnbmF0dXJlLXZhbHVl",
    "dGhpcyBpcyBhIGJhc2ljIGF1dGg=",
)


@pytest.fixture()
def logged(tmp_path):
    path = logs.configure_logging("demoapp", version="0.1.0", data_dir=tmp_path, level="DEBUG")
    yield path
    for handler in list(logging.getLogger().handlers):
        if getattr(handler, "_processcraft", False):
            logging.getLogger().removeHandler(handler)
            handler.close()


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_records_are_json_lines_in_the_data_folder(logged, tmp_path):
    assert logged == tmp_path / "logs" / "demoapp.jsonl"
    before = logs.counts()
    logging.getLogger("demoapp.rounds").warning("round %s slow", 7, extra={"loops": 12})
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("demoapp.rounds").exception("round failed")
    first, second = _records(logged)[-2:]
    assert first["level"] == "WARNING" and first["message"] == "round 7 slow"
    assert first["app"] == "demoapp" and first["version"] == "0.1.0" and first["loops"] == 12
    assert second["level"] == "ERROR" and "ValueError: boom" in second["error"]
    after = logs.counts()
    assert after["warning"] == before["warning"] + 1 and after["error"] == before["error"] + 1


def test_secrets_never_reach_the_log(logged):
    log = logging.getLogger("demoapp.auth")
    log.info("login password=%s token: %s", SECRETS[0], SECRETS[1])
    log.info('{"api_key": "%s"} Authorization: Bearer %s', SECRETS[1], SECRETS[2])
    log.info("header Basic %s and a bare jwt %s", SECRETS[3], SECRETS[2])
    log.info(
        "key -----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY----- end",
    )
    text = logged.read_text(encoding="utf-8")
    for secret in SECRETS:
        assert secret not in text
    assert "PRIVATE KEY-----\nabc" not in text and "\\nabc\\n" not in text
    assert text.count("***") >= 6


def test_redacting_a_long_line_takes_linear_time():
    """A request with a long path is logged: its redaction must not be a way to stall the app."""

    import time

    started = time.perf_counter()
    assert logs.redact("x" * 100_000) == "x" * 100_000
    assert logs.redact("q" * 5000 + " password=hunter2") == "q" * 5000 + " password=***"
    assert time.perf_counter() - started < 0.5  # was 2.6 s for 8,000 letters


def test_rotation_keeps_a_bounded_number_of_files(tmp_path):
    path = logs.configure_logging(
        "rotapp", version="0.1.0", data_dir=tmp_path, max_bytes=2000, backups=2
    )
    try:
        for index in range(200):
            logging.getLogger("rotapp").info("line %s %s", index, "x" * 50)
    finally:
        logs.configure_logging("rotapp", version="0.1.0")
    files = sorted(p.name for p in path.parent.iterdir())
    assert files == ["rotapp.jsonl", "rotapp.jsonl.1", "rotapp.jsonl.2"]


def test_an_unwritable_folder_keeps_the_console(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("")
    assert logs.configure_logging("demoapp", version="0.1.0", data_dir=blocked) is None
    logs.configure_logging("demoapp", version="0.1.0")


def _client(tmp_path):
    fake = FakePlantCraft()
    (tmp_path / "app.toml").write_text('[app]\nid = "demoapp"\nversion = "0.1.0"\n')
    runtime = SimpleNamespace(
        settings=SimpleNamespace(root_path="/demo", processcraft_public_url="/"),
        verifier=fake.verifier("linkcraft"),
        status=lambda: {},
        start=lambda: None,
        shutdown=lambda: None,
    )
    api = suite_api(runtime, title="Demo", version="0.1.0", files=AppFiles("demoapp", tmp_path))
    return fake, TestClient(mount(api, runtime, version="0.1.0"))


def test_each_request_gets_an_id_and_a_log_line(logged, tmp_path):
    _fake, client = _client(tmp_path)
    given = client.get("/demo/api/me", headers={"X-Request-ID": "proxy-abc-123"})
    assert given.headers["x-request-id"] == "proxy-abc-123"
    fresh = client.get("/healthz", headers={"X-Request-ID": "bad id\nwith newline"})
    assert len(fresh.headers["x-request-id"]) == 32
    lines = [r for r in _records(logged) if r["logger"] == "processcraft.requests"]
    assert lines[-2]["request_id"] == "proxy-abc-123" and lines[-2]["status"] == 401
    assert lines[-1]["level"] == "DEBUG" and lines[-1]["message"].startswith("GET /healthz 200")


def test_metrics_need_an_admin_or_the_ops_scope(tmp_path):
    fake, client = _client(tmp_path)
    client.get("/healthz")
    viewer = {"Authorization": f"Bearer {fake.token('operator')}"}
    assert client.get("/demo/api/ops/metrics", headers=viewer).status_code == 403
    monitor = fake.token("processcraft:monitor", apps={"linkcraft": "viewer"}, scope="ops")
    answer = client.get("/demo/api/ops/metrics", headers={"Authorization": f"Bearer {monitor}"})
    body = answer.json()
    assert answer.status_code == 200 and body["app"] == "demoapp" and body["version"] == "0.1.0"
    assert body["requests"]["total"] >= 2 and set(body["logs"]) == {"warning", "error"}
    admin = {"Authorization": f"Bearer {fake.token('admin')}"}
    assert client.get("/demo/api/ops/metrics", headers=admin).status_code == 200


def test_metrics_carry_the_queue_an_app_reports():
    assert "queue" not in ops.metrics("demoapp", "0.1.0")
    try:
        ops.report_queue(lambda: QueueNow(queued=12, running=4, workers=4, delay_seconds=90.0))
        queue = ops.metrics("demoapp", "0.1.0")["queue"]
        assert queue["queued"] == 12 and queue["delay_seconds"] == 90.0
        assert set(queue) == set(ops.QUEUE_KEYS)

        def broken():
            raise RuntimeError("database locked")

        ops.report_queue(broken)
        assert "queue" not in ops.metrics("demoapp", "0.1.0")
    finally:
        ops.report_queue(None)


def test_metrics_carry_the_conditions_an_app_has_open():
    assert "conditions" not in ops.metrics("histcraft", "0.1.0")
    try:
        ops.report_conditions(
            lambda: [
                Condition(name="source.disconnected", key="source:opc-1", summary="opc-1: timeout",
                          subject="source:opc-1"),
                {"name": "point.bad", "key": "point:7", "severity": "warning"},
                {"name": "Not An Event", "key": "x"},  # left out, logged
            ]
        )  # fmt: skip
        found = ops.metrics("histcraft", "0.1.0")["conditions"]
        assert [item["key"] for item in found] == ["source:opc-1", "point:7"]
        assert found[0]["subject"] == "source:opc-1" and "severity" not in found[0]
        assert found[1]["severity"] == "warning"
        ops.report_conditions(
            lambda: [{"name": "point.bad", "key": f"point:{n}"} for n in range(MAX_CONDITIONS + 50)]
        )
        assert len(ops.metrics("histcraft", "0.1.0")["conditions"]) == MAX_CONDITIONS

        def broken():
            raise RuntimeError("database locked")

        # Not read: PlantCraft keeps what it knew rather than closing every condition.
        ops.report_conditions(broken)
        assert "conditions" not in ops.metrics("histcraft", "0.1.0")
    finally:
        ops.report_conditions(None)


def test_schema_stamp_refuses_a_newer_database(tmp_path):
    assert schema_stamp("0.10.3") == 10003 and schema_stamp("1.2.0-rc1") == 1002000
    assert stamp_version(1002000) == "1.2.0"
    with pytest.raises(ValueError):
        schema_stamp("latest")
    path = tmp_path / "app.sqlite3"
    Database(path)  # no version: no stamp, as before
    Database(path, version="0.2.0")
    Database(path, version="0.2.0")
    Database(path, version="0.3.1")
    with pytest.raises(SchemaTooNew) as caught:
        Database(path, version="0.2.0")
    assert "written by version 0.3.1" in str(caught.value) and "rollback" in str(caught.value)
