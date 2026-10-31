"""Operations › Logs and Load alerts (/api/operations/logs, /limits), and the Operations role."""
# ruff: noqa: F811 (the fixture "world" of tests/test_apps_api.py, imported to share it)

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from plantcraft.watch.logs import SuiteLogs, shape
from plantcraft_sdk.server import logs as sdk_logs
from tests.test_apps_api import audit, sign_in, world  # noqa: F401

NOW = datetime.now(timezone.utc)


def _record(minutes_ago: float, level: str, message: str, app: str = "processcraft", **extra):
    moment = (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="milliseconds")
    return {"time": moment, "level": level, "app": app, "logger": app, "message": message, **extra}


class FakeIssuer:
    def __init__(self):
        self.issued: list[dict] = []

    def issue(self, subject, **claims):
        self.issued.append({"subject": subject, **claims})
        return "token", {}


def _servers(answers: dict[str, object]) -> httpx.Client:
    """An HTTP client whose servers answer ``answers[host]`` (a status code or the records)."""

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = answers[request.url.host]
        if isinstance(answer, int):
            return httpx.Response(answer)
        if answer is None:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json={"records": answer, "truncated": False})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    client.seen = seen  # type: ignore[attr-defined]
    return client


def test_the_servers_are_merged_newest_first_and_the_missing_named(tmp_path):
    own = tmp_path / "processcraft.jsonl"
    own.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                _record(30, "INFO", "started"),
                _record(3, "ERROR", "Historian read 504 after 30 s"),
            ]
        )
        + "\n"  # fmt: skip
    )
    http = _servers({
        "histcraft": [_record(1, "ERROR", "write batch 7 failed", app="histcraft"),
                      _record(2, "ERROR", "write batch 12 failed", app="histcraft")],
        "modelcraft": None,  # down
        "doccraft": 404,  # an app older than the route
    })  # fmt: skip
    urls = {name: f"http://{name}:8000/x" for name in ("histcraft", "modelcraft", "doccraft")}
    issuer = FakeIssuer()
    reader = SuiteLogs(issuer, urls, own_file=lambda: own, http=http)
    found = reader.read(level="WARNING", limit=50)
    assert [(r["service"], r["message"]) for r in found["records"]] == [
        ("histcraft", "write batch 7 failed"),
        ("histcraft", "write batch 12 failed"),
        ("processcraft", "Historian read 504 after 30 s"),
    ]
    assert found["read"] == ["histcraft", "processcraft"]
    assert found["missing"] == ["doccraft", "modelcraft"]
    # Numbers fold: the two failed batches are one line of the top.
    assert found["top"][0] == {"service": "histcraft", "level": "ERROR",
                               "message": "write batch # failed", "count": 2}  # fmt: skip
    # Each server got the filters and a token of the ops scope for itself only.
    asked = {request.url.host: dict(request.url.params) for request in http.seen}
    assert asked["histcraft"]["level"] == "WARNING" and asked["histcraft"]["limit"] == "50"
    assert {item["audience"] for item in issuer.issued} == set(urls)
    assert all(item["scope"] == "ops" for item in issuer.issued)
    # Only some servers, and a limit across all of them.
    only = reader.read(services=["histcraft", "nope"], limit=1)
    assert [r["service"] for r in only["records"]] == ["histcraft"] and only["truncated"]


def test_shape_folds_what_varies():
    assert (
        shape("worker 3 killed after 12.5 s (id 9f3a2b1c00)") == "worker # killed after # s (id #)"
    )
    assert shape('source "opc-1" timeout') == "source # timeout"


# The routes -------------------------------------------------------------------------------


def _give_operations(client, username):
    payload = {
        "display_name": "Eng",
        "access_level": "editor",
        "app_roles": {"operations": "viewer"},
    }
    answer = client.put(f"/api/users/{username}", json=payload)
    assert answer.status_code == 200, answer.text


def test_the_operations_role_opens_status_and_logs_but_not_the_limits(world, tmp_path):
    admin = sign_in(world.client())
    eng = sign_in(world.client(), "eng", "password-123")
    assert eng.get("/api/operations/health").status_code == 403
    assert eng.get("/api/operations/logs").status_code == 403
    _give_operations(admin, "eng")
    health = eng.get("/api/operations/health")
    assert health.status_code == 200 and health.json()["limits"]["cpu_warning"] == 80.0
    assert eng.get("/api/operations/limits").status_code == 200
    assert eng.put("/api/operations/limits", json={"cpu_warning": 70}).status_code == 403
    # Backups and updates stay with the administrators.
    assert eng.get("/api/operations").status_code == 403
    assert eng.post("/api/operations/backup", json={}).status_code == 403


def test_limits_are_changed_by_an_admin_checked_and_audited(world):
    client = sign_in(world.client())
    assert client.get("/api/operations/limits").json()["minutes"] == 5
    stored = client.put("/api/operations/limits", json={"cpu_warning": 70, "minutes": 10}).json()
    assert stored["cpu_warning"] == 70 and stored["minutes"] == 10
    bad = client.put("/api/operations/limits", json={"cpu_warning": 99, "cpu_critical": 90})
    assert bad.status_code == 422 and "critical" in bad.json()["detail"]
    assert client.get("/api/operations/limits").json()["cpu_warning"] == 70
    assert audit(client, "operations.limits")


def test_logs_read_platforms_own_file_with_filters_and_are_audited(world, tmp_path):
    client = sign_in(world.client())
    rt = client.app.state.runtime
    own = tmp_path / "own.jsonl"
    own.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                _record(600, "ERROR", "too old"),
                _record(5, "WARNING", "slow query 4 s"),
                _record(4, "INFO", "fine"),
            ]
        )
        + "\n"  # fmt: skip
    )
    rt.suite_logs = SuiteLogs(rt.tokens, {}, own_file=lambda: own)
    body = client.get("/api/operations/logs", params={"level": "warning"}).json()
    # The last 6 hours by default: the error of 10 hours ago is not in.
    assert [r["message"] for r in body["records"]] == ["slow query 4 s"]
    assert body["services"] == ["processcraft"] and body["missing"] == []
    longer = client.get("/api/operations/logs", params={"level": "ERROR", "hours": 24}).json()
    assert [r["message"] for r in longer["records"]] == ["too old"]
    assert client.get("/api/operations/logs", params={"level": "LOUD"}).status_code == 422
    assert client.get("/api/operations/logs", params={"since": "soon"}).status_code == 422
    assert client.get("/api/operations/logs", params={"hours": 0}).status_code == 422
    assert audit(client, "operations.logs.read")


def test_the_platform_reads_the_file_its_own_logging_writes(tmp_path):
    path = sdk_logs.configure_logging("processcraft", version="0", data_dir=tmp_path)
    try:
        logging.getLogger("plantcraft.test").error("disk check failed: 3 % free")
        found = SuiteLogs(FakeIssuer(), {}).read(level="ERROR", text="disk check")
        assert path is not None and [r["message"] for r in found["records"]] == [
            "disk check failed: 3 % free"]  # fmt: skip
    finally:
        for handler in list(logging.getLogger().handlers):
            if getattr(handler, "_processcraft", False):
                logging.getLogger().removeHandler(handler)
                handler.close()
