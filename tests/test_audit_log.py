"""The audit log: sign-ins, failed sign-ins and sign-outs are recorded, and admins read it
(Setup › Audit log, ``GET /api/audit`` and its CSV)."""

from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from tests.test_route_permissions import ADMIN_PASSWORD, _login, app  # noqa: F401


def _actions(rows):
    return [(row["action"], row["username"]) for row in rows]


def test_sign_ins_and_sign_outs_are_in_the_audit_log(app):  # noqa: F811
    with TestClient(app):
        wrong = TestClient(app)
        assert (
            wrong.post("/api/login", json={"username": "vera", "password": "nope"}).status_code
            == 401
        )
        vera = _login(app, "vera", "vera-strong-password")
        assert vera.post("/api/logout").status_code == 200
        admin = _login(app, "admin", ADMIN_PASSWORD)
        rows = admin.get("/api/audit", params={"action": "session"}).json()["rows"]
    found = _actions(rows)
    assert ("session.sign_in_failed", "vera") in found
    assert ("session.sign_in", "vera") in found
    assert ("session.sign_out", "vera") in found
    assert ("session.sign_in", "admin") in found
    failed = next(row for row in rows if row["action"] == "session.sign_in_failed")
    assert failed["detail"]["reason"] == "password" and failed["detail"]["address"]
    signed = next(
        row for row in rows if row["action"] == "session.sign_in" and row["username"] == "vera"
    )
    assert signed["detail"]["method"] == "local" and signed["app_id"] == "processcraft"


def test_the_audit_log_filters_and_downloads_as_csv(app):  # noqa: F811
    runtime = app.state.runtime
    runtime.workspace.audit.record("eddie", "asset.update", "asset:fic-1", {"name": "=HYPERLINK()"})
    runtime.workspace.audit.record("eddie", "asset_type.delete", "asset_type:x")
    with TestClient(app):
        admin = _login(app, "admin", ADMIN_PASSWORD)
        rows = admin.get("/api/audit", params={"action": "asset", "username": "Eddie"}).json()[
            "rows"
        ]
        assert _actions(rows) == [("asset.update", "eddie")]
        reply = admin.get("/api/audit.csv", params={"username": "eddie"})
    assert reply.status_code == 200 and reply.headers["content-type"].startswith("text/csv")
    table = list(csv.reader(io.StringIO(reply.text)))
    assert table[0] == ["at", "username", "app_id", "action", "subject", "detail"]
    assert {row[3] for row in table[1:]} == {"asset.update", "asset_type.delete"}
    assert all(not cell.startswith("=") for row in table for cell in row)


def test_quick_filters_volume_and_paging(app):  # noqa: F811
    """The page's quick filters, its chart of rows per hour and "Load more"."""

    runtime = app.state.runtime
    for number in range(5):
        runtime.workspace.audit.record("eddie", "asset.update", f"asset:p-{number}")
    with TestClient(app):
        assert (
            TestClient(app)
            .post("/api/login", json={"username": "vera", "password": "nope"})
            .status_code
            == 401
        )
        admin = _login(app, "admin", ADMIN_PASSWORD)
        get = lambda path, **params: admin.get(path, params=params)  # noqa: E731
        changes = get("/api/audit", kind="changes").json()["rows"]
        assert changes and all(not row["action"].startswith("session.") for row in changes)
        failed = get("/api/audit", kind="failed").json()["rows"]
        assert _actions(failed) == [("session.sign_in_failed", "vera")]
        signed = get("/api/audit", kind="sign_ins").json()["rows"]
        assert {row["action"] for row in signed} <= {"session.sign_in", "session.sign_out"}
        assert get("/api/audit", kind="nope").status_code == 422
        assert get("/api/audit", start="yesterday").status_code == 422

        first = get("/api/audit", username="eddie", limit=2).json()
        assert first["truncated"] and len(first["rows"]) == 2
        more = get(
            "/api/audit", username="eddie", limit=10, before_id=first["rows"][-1]["audit_id"]
        ).json()["rows"]
        assert len(more) == 3 and more[0]["audit_id"] < first["rows"][-1]["audit_id"]

        volume = get("/api/audit/volume", days=1).json()
        assert volume["bucket"] == "hour"
        assert sum(item["total"] for item in volume["buckets"]) >= 7
        assert sum(item["failed"] for item in volume["buckets"]) == 1
        assert volume["buckets"][0]["at"].endswith(":00:00Z")
        assert {"username": "eddie", "count": 5} in volume["people"]
        assert get("/api/audit/volume", days=30).json()["bucket"] == "day"
        # A fixed period: nothing in a year long gone.
        old = get("/api/audit", start="2001-01-01T00:00:00Z", end="2001-12-31T00:00:00Z").json()
        assert old["rows"] == []
