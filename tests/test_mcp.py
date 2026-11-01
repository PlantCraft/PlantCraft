"""AI assistant access: the read-only MCP server, its switch and the people's access tokens."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.assistant_access import mcp
from tests.test_access import PASSWORD, _create, _login, _scenario

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}},
}


@pytest.fixture()
def signed(tmp_path, monkeypatch):
    _scenario(tmp_path, monkeypatch)
    secret = tmp_path / "secret"
    secret.write_text("admin-secret")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    with TestClient(create_app()) as client:
        login = {"username": "admin", "password": "admin-secret"}
        assert client.post("/api/login", json=login).status_code == 200
        yield client


def _rpc(app, token, method, params=None, request_id=2):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return TestClient(app).post("/mcp", json=body, headers={"Authorization": f"Bearer {token}"})


def _call(app, token, name, arguments=None):
    answer = _rpc(app, token, "tools/call", {"name": name, "arguments": arguments or {}})
    assert answer.status_code == 200, answer.text
    return answer.json()


def _on(admin):
    saved = admin.put("/api/assistant-access", json={"enabled": True, "max_days": 30})
    assert saved.status_code == 200 and saved.json()["enabled"] is True


def test_off_by_default_and_only_an_admin_turns_it_on(signed):
    assert signed.get("/api/assistant-access").json()["enabled"] is False
    assert TestClient(signed.app).post("/mcp", json=INIT).status_code == 404
    refused = signed.post("/api/assistant-access/mine", json={"label": "Claude"})
    assert refused.status_code == 409
    _create(signed, "leitor", "viewer")
    viewer = _login(signed.app, "leitor")
    assert viewer.put("/api/assistant-access", json={"enabled": True}).status_code == 403
    assert viewer.get("/api/assistant-access").status_code == 403
    assert viewer.get("/api/assistant-access/mine").json()["can_create"] is False


def test_installation_switch_keeps_it_off(signed, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_MCP", "off")
    assert signed.put("/api/assistant-access", json={"enabled": True}).status_code == 409
    assert signed.get("/api/assistant-access").json()["allowed"] is False


def test_a_person_reads_the_plant_as_themselves(signed):
    _on(signed)
    _create(signed, "leitor", "viewer")
    viewer = _login(signed.app, "leitor")
    created = viewer.post("/api/assistant-access/mine", json={"label": "Claude Desktop"})
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    assert token.startswith("pcat_")
    listed = viewer.get("/api/assistant-access/mine").json()
    assert listed["endpoint"].endswith("/mcp")
    assert [item["label"] for item in listed["tokens"]] == ["Claude Desktop"]
    assert "token_hash" not in json.dumps(listed) and token not in json.dumps(listed)

    init = TestClient(signed.app).post(
        "/mcp", json=INIT, headers={"Authorization": f"Bearer {token}"}
    )
    assert init.status_code == 200
    assert init.json()["result"]["protocolVersion"] == "2025-06-18"
    assert init.json()["result"]["capabilities"] == {"tools": {"listChanged": False}}
    notified = TestClient(signed.app).post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert notified.status_code == 202
    tools = _rpc(signed.app, token, "tools/list").json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == set(mcp.BY_NAME)
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)

    me = json.loads(_call(signed.app, token, "whoami")["result"]["content"][0]["text"])
    assert me["username"] == "leitor" and me["level"] == "viewer"
    signals = _call(signed.app, token, "search_signals", {"query": "pv", "limit": 5})
    found = json.loads(signals["result"]["content"][0]["text"])
    assert found and all(item["id"].startswith("scenario:") for item in found)
    series = _call(
        signed.app,
        token,
        "read_series",
        {
            "signal_ids": [found[0]["id"]],
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-08T00:00:00Z",
        },
    )
    assert series["result"]["isError"] is False, series
    read = json.loads(series["result"]["content"][0]["text"])
    assert read["series"][0]["signal"] == found[0]["id"]
    too_long = {"signal_ids": [found[0]["id"]], "start": "2020-01-01", "end": "2030-01-01"}
    refused = _call(signed.app, token, "read_series", too_long)["result"]
    assert refused["isError"] is True and "366 days" in refused["content"][0]["text"]
    # A read too fine for a trend is refused before it is made, with the step that fits.
    every_second = {**too_long, "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"}
    fine = _call(signed.app, token, "read_series", {**every_second, "step_seconds": 1})["result"]
    assert fine["isError"] is True and "step_seconds of 5 or more" in fine["content"][0]["text"]
    assets = _call(signed.app, token, "search_assets", {"kind": "loop", "limit": 3})
    assert len(json.loads(assets["result"]["content"][0]["text"])) <= 3
    missing = _call(signed.app, token, "get_asset", {"asset_id": "nope/../x"})
    assert (
        missing["result"]["isError"] is True
        and "HTTP 404" in missing["result"]["content"][0]["text"]
    )

    audit = signed.app.state.runtime.workspace.audit.list(limit=50)
    calls = [row for row in audit if row["action"] == "mcp.tool"]
    assert calls and {row["username"] for row in calls} == {"leitor"}


def test_bad_requests_are_refused_without_running_anything(signed):
    _on(signed)
    token = signed.post("/api/assistant-access/mine", json={}).json()["token"]
    plain = TestClient(signed.app)
    assert plain.post("/mcp", json=INIT).status_code == 401
    assert (
        plain.post("/mcp", json=INIT, headers={"Authorization": "Bearer pcat_x.y"}).status_code
        == 401
    )
    other_site = {"Authorization": f"Bearer {token}", "Origin": "https://evil.example"}
    assert plain.post("/mcp", json=INIT, headers=other_site).status_code == 403
    assert plain.get("/mcp", headers={"Authorization": f"Bearer {token}"}).status_code == 405
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    assert plain.post("/mcp", content=b"{nope", headers=headers).json()["error"]["code"] == -32700
    assert plain.post("/mcp", json=[INIT], headers=headers).json()["error"]["code"] == -32600
    assert _rpc(signed.app, token, "resources/list").json()["error"]["code"] == -32601
    for arguments in ({"nope": 1}, {"limit": 0}, {"query": "x" * 500}, {"limit": True}):
        answer = _rpc(
            signed.app, token, "tools/call", {"name": "search_signals", "arguments": arguments}
        )
        assert answer.json()["error"]["code"] == -32602, arguments
    unknown = _rpc(signed.app, token, "tools/call", {"name": "write_value", "arguments": {}})
    assert unknown.json()["error"]["code"] == -32602
    missing = _rpc(signed.app, token, "tools/call", {"name": "get_signal", "arguments": {}})
    assert "missing arguments" in missing.json()["error"]["message"]


def test_revoking_turning_off_or_losing_access_stops_a_token(signed):
    _on(signed)
    _create(signed, "engenheira", "editor")
    person = _login(signed.app, "engenheira")
    first = person.post("/api/assistant-access/mine", json={"label": "a"}).json()
    second = person.post("/api/assistant-access/mine", json={"label": "b"}).json()
    assert _rpc(signed.app, first["token"], "ping").json()["result"] == {}

    assert person.delete(f"/api/assistant-access/mine/{first['token_id']}").status_code == 200
    assert _rpc(signed.app, first["token"], "ping").status_code == 401
    # Somebody else's token is not theirs to revoke; an admin may revoke any.
    admin_token = signed.post("/api/assistant-access/mine", json={}).json()
    assert person.delete(f"/api/assistant-access/mine/{admin_token['token_id']}").status_code == 404
    assert signed.delete(f"/api/assistant-access/tokens/{second['token_id']}").status_code == 200
    assert _rpc(signed.app, second["token"], "ping").status_code == 401

    third = person.post("/api/assistant-access/mine", json={}).json()
    off = {"display_name": "Eng", "role": "", "access_level": "editor", "active": False}
    assert signed.put("/api/users/engenheira", json=off).status_code == 200
    assert _rpc(signed.app, third["token"], "ping").status_code == 403

    signed.put("/api/assistant-access", json={"enabled": False, "max_days": 30})
    assert _rpc(signed.app, admin_token["token"], "ping").status_code == 404


def test_a_token_lasts_at_most_the_days_the_admin_allows(signed):
    signed.put("/api/assistant-access", json={"enabled": True, "max_days": 7})
    record = signed.post("/api/assistant-access/mine", json={"days": 90}).json()
    from datetime import datetime

    created = datetime.fromisoformat(record["created_at"])
    expires = datetime.fromisoformat(record["expires_at"])
    assert 6.9 < (expires - created).total_seconds() / 86400 <= 7.01
    assert PASSWORD  # the shared helpers' password is the one _login uses


def test_every_tool_only_reads():
    """The assistant's tools never write (OWASP LLM06, excessive agency): each one is a GET of
    API v1, or the one POST that reads a series. A new tool that writes fails here."""

    reads_by_post = {"/api/v1/series"}
    for tool in mcp.TOOLS:
        arguments = {
            name: (["plantcraft:X"] if spec.get("type") == "array" else "x")
            for name, spec in tool.properties.items()
            if name in tool.required
        }
        try:
            method, path, _values = tool.request(arguments)
        except (ValueError, KeyError, TypeError):
            continue
        assert path.startswith("/api/v1/"), f"{tool.name} reads outside API v1: {path}"
        assert method == "GET" or (method == "POST" and path in reads_by_post), (
            f"{tool.name} would {method} {path}"
        )


def test_a_cut_list_says_its_total_and_app_objects_are_found_without_long_fields():
    items = [{"id": f"b{n}", "name": f"Block {n}", "code": "x" * 400} for n in range(71)]
    cut = mcp._first(items, {"limit": 30})
    assert cut["total"] == 71 and len(cut["items"]) == 30
    assert mcp._first(items[:3], {"limit": 30}) == items[:3]
    payload = {"format": "plantcraft-objects/1", "kind": "block", "items": items}
    found = mcp._objects(payload, {"query": "block 7"})
    assert found["total"] == 2 and {item["id"] for item in found["items"]} == {"b7", "b70"}
    assert all("code" not in item for item in found["items"])
    tool = mcp.BY_NAME["get_app_object"]
    args = {"app": "linkcraft", "kind": "block", "object_id": "frozen_value"}
    assert tool.request(args) == ("GET", "/api/v1/apps/linkcraft/objects/block/frozen_value", {})


def test_an_apps_objects_are_kept_by_their_fields():
    payload = {
        "items": [
            {"id": "a1", "name": "LIC-1113 high", "active": True, "priority": "high"},
            {"id": "a2", "name": "FIC-1201 low", "active": False, "priority": "high"},
        ]
    }
    found = mcp._objects(payload, {"where": "active=true, priority=high"})
    assert [item["id"] for item in found["items"]] == ["a1"] and found["total"] == 1


def test_results_are_counted_per_unit_most_problems_first():
    unit_a, unit_b = {"id": "u-a", "name": "Unit A"}, {"id": "u-b", "name": "Unit B"}
    rows = [
        {"status": "ok", "group": unit_a},
        {"status": "alarm", "group": unit_b},
        {"status": "warning", "group": unit_b},
        {"status": "ok", "group": None},
    ]
    counted = mcp._counted(rows)
    assert counted["results"] == 4
    first, second, third = counted["groups"]
    assert first == {"id": "u-b", "name": "Unit B", "total": 2, "problems": 2,
                     "status": {"alarm": 1, "warning": 1}}  # fmt: skip
    assert (second["name"], third["name"]) == ("(not under one)", "Unit A")
    tool = next(tool for tool in mcp.TOOLS if tool.name == "count_results")
    assert tool.request({})[2] == {"group": "unit"}


def test_equipment_and_actions_are_read_without_an_asset(signed):
    """Round 4 (2026-10-26): kind=equipment found none of the plant's pumps, list_actions was
    taken for one asset's."""

    _on(signed)
    token = signed.post("/api/assistant-access/mine", json={"label": "Eval"}).json()["token"]
    signed.app.state.runtime.workspace.assets.save("p-101", name="Feed pump", kind="pump")
    action = {"title": "Check the seal", "owner": "admin", "due_at": "2026-10-28"}
    assert signed.post("/api/actions", json=action).status_code in (200, 201)

    def read(name, arguments):
        answer = _call(signed.app, token, name, arguments)["result"]
        assert answer["isError"] is False, answer
        return json.loads(answer["content"][0]["text"])

    found = read("search_assets", {"kind": "equipment", "limit": 200})
    found = found["items"] if isinstance(found, dict) and "items" in found else found
    assert "p-101" in {item["id"] for item in found}
    actions = read("list_actions", {"status": ["open", "in_progress", "blocked"]})
    assert [item["title"] for item in actions["items"]] == ["Check the seal"]


def test_apps_are_found_by_name_and_stale_results_are_said_apart():
    assert [mcp.app_id(name) for name in ("models", "Analytics", "link", "View", "alarmcraft")] == [
        "modelcraft", "linkcraft", "linkcraft", "dashcraft", "alarmcraft",
    ]  # fmt: skip
    tool = mcp.BY_NAME["list_app_objects"]
    assert (
        tool.request({"app": "Models", "kind": "model"})[1]
        == "/api/v1/apps/modelcraft/objects/model"
    )
    rows = [
        {"subject": "signal:a", "status": "unknown", "stale": True, "at": "2026-10-26T21:13:00Z"},
        {"subject": "signal:b", "status": "ok", "stale": False, "at": "2026-10-26T23:00:00Z"},
    ]
    shaped = mcp._results(rows, {})
    assert shaped["total"] == 2 and shaped["items"] == rows
    assert shaped["note"].startswith(
        "1 of 2 results are stale (the newest of them from 2026-10-26T21:13"
    )
    assert mcp._results(rows[1:], {}) == rows[1:]


def test_a_periods_statistics_read_every_point_with_the_times_of_min_and_max():
    method, path, body = mcp.BY_NAME["signal_stats"].request(
        {"signal_ids": ["s:a"], "start": "2026-10-25T03:00:00Z", "end": "2026-10-26T03:00:00Z"}
    )
    assert (method, path, body["step"]) == ("POST", "/api/v1/series", 5)
    payload = {
        "series": [
            {"signal": "s:a", "unit": "m3/h", "t": ["t0", "t1", "t2"], "v": [56.0, 58.12, None]}
        ]
    }
    [stats] = mcp._series_stats(payload)["series"]
    assert stats == {"signal": "s:a", "unit": "m3/h", "count": 2, "mean": 57.06, "std": 1.06,
                     "min": 56.0, "min_at": "t0", "max": 58.12, "max_at": "t1", "first": 56.0,
                     "last": 58.12}  # fmt: skip


def test_a_periods_statistics_give_a_loops_error_point_by_point():
    """PV minus setpoint, paired by time: its mean absolute value is not |mean PV - mean SP|."""

    import pytest

    tool = mcp.BY_NAME["signal_stats"]
    args = {"signal_ids": ["s:pv"], "minus": ["s:sp"], "start": "2026-10-25T03:00:00Z",
            "end": "2026-10-26T03:00:00Z"}  # fmt: skip
    method, path, body = tool.request(args)
    assert body["signals"] == ["s:pv", "s:sp"]
    payload = {
        "series": [
            {"signal": "s:pv", "unit": "", "t": ["t0", "t1", "t2"], "v": [11.0, 9.0, 12.0]},
            {"signal": "s:sp", "unit": "", "t": ["t0", "t1", "t2"], "v": [10.0, 10.0, None]},
        ]
    }
    shaped = mcp._series_stats(payload, args)
    assert [item["signal"] for item in shaped["series"]] == ["s:pv"]
    [error] = shaped["differences"]
    assert (error["minus"], error["count"], error["mean"], error["mean_abs"]) == (
        "s:sp",
        2,
        0.0,
        1.0,
    )
    with pytest.raises(ValueError, match="one signal for each"):
        tool.request({**args, "minus": ["s:sp", "s:x"]})
    with pytest.raises(ValueError, match="at most"):
        tool.request({"signal_ids": [f"s:{i}" for i in range(15)],
                      "minus": [f"s:sp{i}" for i in range(15)]})  # fmt: skip


def test_a_list_in_pages_is_read_whole_or_says_it_goes_on(monkeypatch):
    """A list route answers in pages (``X-Next-Cursor``): a tool reads them, and says when it
    stopped before the end (2026-10-27: 5,000 bench loops hid the plant's results)."""

    import asyncio

    import httpx

    def answer(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("cursor") or 0)
        more = {"X-Next-Cursor": str(page + 1)} if page < 4 else {}
        return httpx.Response(200, json=[{"page": page}], headers=more)

    async def read() -> mcp.Paged:
        transport = httpx.MockTransport(answer)
        async with httpx.AsyncClient(transport=transport, base_url="http://x") as client:
            return mcp._payload(await mcp._get(client, "/api/v1/results", {}))

    whole = asyncio.run(read())
    assert [item["page"] for item in whole] == [0, 1, 2, 3, 4] and not whole.truncated
    monkeypatch.setattr(mcp, "MAX_PAGES", 3)
    cut = asyncio.run(read())
    assert len(cut) == 3 and cut.truncated


def test_my_actions_are_the_ones_i_own():
    payload = {"items": [{"title": "A", "owner": "camila"}, {"title": "B", "owner": "Admin"}]}
    assert mcp._owned(payload, {"owner": "admin"})["items"] == [{"title": "B", "owner": "Admin"}]
    assert mcp._owned(payload, {"owner": "tiago"})["note"] == "none is owned by tiago"
    assert mcp._owned(payload, {}) == payload
    assert mcp.BY_NAME["list_actions"].request({"owner": "admin"})[2]["limit"] == 500


def test_an_unknown_type_says_so_and_a_typographic_apostrophe_says_not_found():
    from plantcraft.assistant_chat.evals import says_not_found

    assert mcp._matching_assets([], {"kind": "control_loop"})["note"].startswith("no asset of type")
    assert says_not_found("I couldn\u2019t find XQ-4242.PV.")
