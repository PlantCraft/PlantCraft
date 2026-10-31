"""Reading a server's own log back with filters (``GET /api/ops/logs``)."""

import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from plantcraft_sdk.server import logread, logs
from plantcraft_sdk.server.files import AppFiles
from plantcraft_sdk.server.web import mount, suite_api
from plantcraft_sdk.testing import FakePlantCraft

T0 = datetime(2026, 10, 31, 3, 0, tzinfo=timezone.utc)


def _line(minutes: int, level: str, message: str, **extra) -> str:
    moment = (T0 + timedelta(minutes=minutes)).isoformat(timespec="milliseconds")
    record = {"time": moment, "level": level, "app": "modelcraft", "logger": "modelcraft.study",
              "message": message, **extra}  # fmt: skip
    return json.dumps(record)


@pytest.fixture()
def files(tmp_path):
    """Two rotated copies and the current file, oldest lines in ``.2``."""

    path = tmp_path / "modelcraft.jsonl"
    path.with_name("modelcraft.jsonl.2").write_text(
        "\n".join([_line(0, "INFO", "study started"), _line(1, "WARNING", "memory 1.9 of 2.0 GB")])
        + "\n"
    )
    path.with_name("modelcraft.jsonl.1").write_text(
        "\n".join(
            [
                _line(2, "INFO", "compiling FIC-1003"),
                "not json at all",
                _line(
                    3,
                    "ERROR",
                    "worker killed (exit 137)",
                    request_id="a91f0000",
                    error="Traceback ...\nMemoryError",
                ),
            ]
        )
        + "\n"  # fmt: skip
    )
    path.write_text(
        "\n".join(
            [
                _line(
                    4,
                    "INFO",
                    "GET /model/api/studies 200",
                    logger="processcraft.requests",
                    request_id="a91f0000",
                ),  # fmt: skip
                _line(5, "DEBUG", "cache hit"),
            ]
        )
        + "\n"  # fmt: skip
    )
    return path


def test_newest_first_across_the_rotated_files(files):
    found = logread.read_logs(files)
    messages = [item["message"] for item in found["records"]]
    assert messages[0] == "cache hit" and messages[-1] == "study started"
    assert len(messages) == 6 and not found["truncated"]  # the line that is not JSON is skipped


def test_filters_level_text_request_logger_and_time(files):
    def messages(**kwargs):
        return [item["message"] for item in logread.read_logs(files, **kwargs)["records"]]

    assert messages(level="WARNING") == ["worker killed (exit 137)", "memory 1.9 of 2.0 GB"]
    assert messages(level="error") == ["worker killed (exit 137)"]
    # Text is looked for in the error too, ignoring case.
    assert messages(text="memoryerror") == ["worker killed (exit 137)"]
    assert messages(request_id="a91f0000") == [
        "GET /model/api/studies 200",
        "worker killed (exit 137)",
    ]
    assert messages(logger="processcraft") == ["GET /model/api/studies 200"]
    assert messages(logger="modelcraft.stu") == []  # a logger and its children, not a prefix
    window = messages(since=T0 + timedelta(minutes=2), until=T0 + timedelta(minutes=3, seconds=30))
    assert window == ["worker killed (exit 137)", "compiling FIC-1003"]


def test_limit_and_missing_files(files, tmp_path):
    found = logread.read_logs(files, limit=2)
    assert len(found["records"]) == 2 and found["truncated"]
    assert logread.read_logs(tmp_path / "nothing.jsonl") == {
        "records": [], "truncated": False, "scanned_bytes": 0}  # fmt: skip
    assert logread.read_logs(None)["records"] == []


def test_a_long_record_is_clipped(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text(_line(0, "ERROR", "x" * 20_000) + "\n")
    assert len(logread.read_logs(path)["records"][0]["message"]) == logread.MAX_TEXT


@pytest.fixture()
def client(tmp_path):
    logs.configure_logging("demoapp", version="0.1.0", data_dir=tmp_path, level="DEBUG")
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
    yield fake, TestClient(mount(api, runtime, version="0.1.0"))
    for handler in list(logging.getLogger().handlers):
        if getattr(handler, "_processcraft", False):
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_the_route_needs_the_ops_scope_and_filters(client):
    fake, http = client
    logging.getLogger("demoapp.rounds").warning("round 7 slow, password=hunter2")
    logging.getLogger("demoapp.rounds").info("round 8 fine")
    viewer = {"Authorization": f"Bearer {fake.token('operator')}"}
    assert http.get("/demo/api/ops/logs", headers=viewer).status_code == 403
    monitor = fake.token("processcraft:monitor", apps={"linkcraft": "viewer"}, scope="ops")
    headers = {"Authorization": f"Bearer {monitor}"}
    body = http.get("/demo/api/ops/logs", params={"level": "WARNING", "logger": "demoapp"},
                    headers=headers).json()  # fmt: skip
    assert body["app"] == "demoapp" and [item["message"] for item in body["records"]] == [
        "round 7 slow, password=***"]  # fmt: skip
    assert (
        http.get("/demo/api/ops/logs", params={"level": "LOUD"}, headers=headers).status_code == 422
    )
    assert (
        http.get("/demo/api/ops/logs", params={"since": "yesterday"}, headers=headers).status_code
        == 422
    )
    assert (
        http.get("/demo/api/ops/logs", params={"limit": 5000}, headers=headers).status_code == 422
    )
    admin = {"Authorization": f"Bearer {fake.token('admin')}"}
    assert http.get("/demo/api/ops/logs", params={"text": "round 8"}, headers=admin).json()[
        "records"
    ]
