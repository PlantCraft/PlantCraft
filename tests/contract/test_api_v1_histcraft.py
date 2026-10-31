"""API v1 with HistCraft as the data layer (``HISTCRAFT_URL``), against a stub (no network).

PlantCraft checks the caller as always, then forwards to ``{HISTCRAFT_URL}/api/v1/data/...``
with a token it issues to itself (``aud: histcraft``, ``sub: app:processcraft``,
``apps: {histcraft: editor}``). HistCraft's 4xx about the request and its 504 (a read past its
time limit) reach the caller; its other failures are a 502 and a timeout a 504. Sources live in HistCraft too: the Sources page's
routes forward there, and no plant source is read by PlantCraft.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

import httpx
import pytest

from plantcraft.platform.datalayer import DataLayerError
from plantcraft_sdk import jwt
from tests.contract.test_api_v1 import ADMIN, PASSWORD, SpySource, _app_key, _as, _auth, _rt

URL = "http://histcraft.test/hist"
SIGNAL = {
    "id": "plc:FIC-101.PV",
    "name": "Feed flow",
    "source": "plc",
    "unit": "m3/h",
    "description": "",
    "low": None,
    "high": None,
    "kind": "number",
    "mode": "both",
}
SERIES = {
    "signal": "plc:FIC-101.PV",
    "kind": "number",
    "t": ["2026-10-19T06:00:00+00:00"],
    "v": [1.5],
}


def _public(source: dict) -> dict:
    """A source as HistCraft lists it: no password, ``has_password`` instead."""

    fields = (
        "id",
        "name",
        "kind",
        "endpoint",
        "namespace_uri",
        "username",
        "password_env",
        "options",
    )
    return {
        **{key: source.get(key) for key in fields},
        "default_mode": "both",
        "has_password": bool(source.get("password")),
    }


class FakeHistCraft:
    """HistCraft's data API as PlantCraft calls it: records each request, answers v1 shapes."""

    def __init__(self, keys):
        self.keys = keys
        self.requests: list[dict] = []
        self.fail: int | None = None
        self.timeout = False
        self.sources = {
            "plc": {
                "id": "plc",
                "name": "PLC",
                "kind": "opcua",
                "endpoint": "opc.tcp://plc:4840/",
                "namespace_uri": "urn:plc",
                "password": "never-shown",
                "options": {"timeout_seconds": 10},
                "has_signals": True,
            }
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        prefix = "/hist/api/v1/data"
        assert request.url.path.startswith(prefix), request.url.path
        path = unquote(request.url.path[len(prefix) :])
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        claims = jwt.decode(token, self.keys(), "histcraft")
        body = json.loads(request.content) if request.content else None
        self.requests.append(
            {
                "method": request.method,
                "path": path,
                "query": dict(request.url.params),
                "body": body,
                "claims": claims,
            }
        )
        if self.timeout:
            raise httpx.ReadTimeout("slow", request=request)
        if self.fail:
            return httpx.Response(self.fail, json={"detail": "HistCraft says no."})
        method = request.method
        if method == "GET" and path == "/signals":
            return httpx.Response(200, json=[SIGNAL])
        if method == "GET" and path.endswith("/series"):
            if "run" in request.url.params or "runs" in request.url.params:
                run = {"run_at": "2026-10-19T00:00:00+00:00", "t": SERIES["t"], "v": SERIES["v"]}
                return httpx.Response(
                    200, json={"signal": SIGNAL["id"], "kind": "runs", "runs": [run]}
                )
            return httpx.Response(200, json=SERIES)
        if method == "GET" and path.endswith("/runs"):
            listed = [{"run_at": "2026-10-19T00:00:00+00:00", "start": None, "end": None, "n": 0}]
            return httpx.Response(200, json={"signal": SIGNAL["id"], "runs": listed})
        if method == "GET" and path.endswith("/value"):
            value = {
                "signal": SIGNAL["id"],
                "agg": "last",
                "window": "1h",
                "value": 1.5,
                "at": SERIES["t"][0],
            }
            return httpx.Response(200, json=value)
        if method == "GET" and path.startswith("/signals/"):
            if path[len("/signals/") :] in (SIGNAL["id"], "FIC-101.PV"):
                return httpx.Response(200, json=SIGNAL)
            return httpx.Response(404, json={"detail": "Signal not found."})
        if method == "DELETE" and path.startswith("/signals/"):
            if path.endswith(":gone"):
                return httpx.Response(404, json={"detail": "Signal not found."})
            return httpx.Response(204)
        if method == "PATCH" and path.startswith("/signals/"):
            signal_id = path[len("/signals/") :]
            if signal_id.startswith("app:"):
                return httpx.Response(422, json={"detail": "Derived signals are the app's."})
            if signal_id.endswith(":gone"):
                return httpx.Response(404, json={"detail": "Signal not found."})
            return httpx.Response(200, json={**SIGNAL, "id": signal_id, "enabled": body["enabled"]})
        if method == "POST" and path == "/sources/test":
            assert "signals" not in body and isinstance(body["username"], str)
            if body["endpoint"].startswith("https://down"):
                return httpx.Response(502, json={"detail": "Host down did not answer."})
            return httpx.Response(200, json={"ok": True, "detail": {"server": body["endpoint"]}})
        if method == "POST" and path == "/series":
            series = [{**SERIES, "signal": s} for s in body["signals"] if s.endswith("FIC-101.PV")]
            errors = [
                {"signal": s, "status": 404, "detail": "Signal not found."}
                for s in body["signals"]
                if not s.endswith("FIC-101.PV")
            ]
            return httpx.Response(200, json={"series": series, "errors": errors})
        if method == "POST" and path == "/derived":
            assert body["app"] and all(item["app"] == body["app"] for item in body["series"])
            bad = [item for item in body["series"] if item["signal"].endswith(":refused")]
            errors = [
                {"signal": item["signal"], "status": 403, "detail": "Not yours."} for item in bad
            ]
            return httpx.Response(
                200, json={"written": len(body["series"]) - len(bad), "errors": errors}
            )
        if method == "POST" and path == "/derived/runs":
            assert body["app"] and all("run_at" in item for item in body["series"])
            return httpx.Response(200, json={"written": len(body["series"]), "errors": []})
        if path == "/sources" and method == "GET":
            return httpx.Response(200, json=[_public(item) for item in self.sources.values()])
        if path == "/sources" and method == "POST":
            if body["id"] in self.sources:
                return httpx.Response(409, json={"detail": "A source with this id exists."})
            self.sources[body["id"]] = body
            added = {
                "added": [f"{body['id']}:{tag}" for tag in body.get("signals") or []],
                "skipped": [],
            }
            return httpx.Response(201, json={**_public(body), "signals_added": added})
        if path.startswith("/sources/"):
            source_id, _, action = path[len("/sources/") :].partition("/")
            if source_id not in self.sources:
                return httpx.Response(404, json={"detail": "Source not found."})
            if method == "PUT" and not action:
                assert "signals" not in body
                self.sources[source_id] = body
                return httpx.Response(200, json=_public(body))
            if method == "DELETE" and not action:
                if self.sources[source_id].get("has_signals"):
                    return httpx.Response(409, json={"detail": "The source still has signals."})
                self.sources.pop(source_id)
                return httpx.Response(204)
            if method == "POST" and action == "test":
                if source_id == "pi":
                    return httpx.Response(502, json={"detail": "PI Web API refused basic."})
                return httpx.Response(200, json={"ok": True, "detail": {"server": "PLC 1.0"}})
            if method == "POST" and action == "browse":
                variables = [
                    {
                        "address": f"ns=2;s=V{i}",
                        "tag": f"V{i}",
                        "name": f"V{i}",
                        "path": "Unit",
                        "kind": "number",
                        "step": False,
                        "unit": "",
                        "description": "",
                        "low": None,
                        "high": None,
                    }
                    for i in range(min(body.get("limit", 5000), 7))
                ]
                return httpx.Response(
                    200,
                    json={"variables": variables, "truncated": False, "limit": body.get("limit")},
                )
            if method == "POST" and action == "signals":
                added = [f"{source_id}:{tag}" for tag in body["signals"]]
                return httpx.Response(200, json={"added": added, "skipped": []})
        return httpx.Response(404, json={"detail": "Not Found"})

    def calls(self, method: str | None = None, path: str | None = None) -> list[dict]:
        return [
            item
            for item in self.requests
            if (method is None or item["method"] == method)
            and (path is None or item["path"] == path)
        ]


@pytest.fixture()
def hist(request, monkeypatch):
    """PlantCraft (sign-in on) with HistCraft as its data layer, and the stub it calls."""

    monkeypatch.setenv("HISTCRAFT_URL", URL)
    client = request.getfixturevalue("central")
    rt = _rt(client)
    layer = rt.datalayer
    assert layer.kind == "histcraft"
    fake = FakeHistCraft(rt.tokens.jwks)
    layer.http = httpx.Client(transport=httpx.MockTransport(fake.handle))
    spy = SpySource(rt.platform.sources.primary)
    rt.platform.sources.primary = spy
    client.fake, client.spy = fake, spy
    return client


def _admin(client):
    client.post("/api/login", json={"username": ADMIN, "password": PASSWORD})


def _service(client) -> dict[str, str]:
    key = _app_key(client)["key"]
    grant = client.post("/api/v1/auth/service-token", json={"app": "linkcraft", "key": key})
    return _auth(grant.json()["token"])


def test_v1_reads_are_forwarded_with_processcraft_own_token(hist):
    fake, reader = hist.fake, _as(hist, "op")
    listed = hist.get("/api/v1/signals", params={"q": "feed", "app": "linkcraft"}, headers=reader)
    assert listed.status_code == 200 and listed.json() == [SIGNAL]  # mode passes through
    assert hist.get("/api/v1/signals/plc:FIC-101.PV", headers=reader).json() == SIGNAL
    bare = hist.get("/api/v1/signals/FIC-101.PV", headers=reader)
    assert bare.json()["id"] == "plc:FIC-101.PV"  # HistCraft resolves the bare tag
    series = hist.get(
        "/api/v1/signals/plc:FIC-101.PV/series",
        params={"start": "2026-10-19T00:00:00Z", "step": 60},
        headers=reader,
    )
    assert series.json() == SERIES
    batch = hist.post(
        "/api/v1/series", json={"signals": ["plc:FIC-101.PV", "nope"]}, headers=reader
    ).json()
    assert [item["signal"] for item in batch["series"]] == ["plc:FIC-101.PV"]
    assert batch["errors"][0]["status"] == 404
    value = hist.get(
        "/api/v1/signals/plc:FIC-101.PV/value",
        params={"agg": "last", "window": "2h"},
        headers=reader,
    )
    assert value.json()["value"] == 1.5
    assert fake.calls("GET", "/signals")[0]["query"] == {"q": "feed", "app": "linkcraft"}
    assert fake.calls("GET", "/signals/plc:FIC-101.PV/series")[0]["query"] == {
        "start": "2026-10-19T00:00:00Z",
        "step": "60.0",
    }
    assert fake.calls("GET", "/signals/plc:FIC-101.PV/value")[0]["query"] == {
        "agg": "last",
        "window": "2h",
    }
    closed = {"agg": "mean", "window": "7d", "end": "2026-10-26T00:00:00Z"}
    hist.get("/api/v1/signals/plc:FIC-101.PV/value", params=closed, headers=reader)
    assert fake.calls("GET", "/signals/plc:FIC-101.PV/value")[1]["query"] == closed
    assert fake.calls("POST", "/series")[0]["body"] == {
        "signals": ["plc:FIC-101.PV", "nope"],
        "start": None,
        "end": None,
        "step": None,
    }
    claims = {
        (c["sub"], c["aud"], json.dumps(c["apps"])) for c in (r["claims"] for r in fake.requests)
    }
    assert claims == {("app:processcraft", "histcraft", '{"histcraft": "editor"}')}
    assert len({r["claims"]["iat"] for r in fake.requests}) == 1  # one token, cached
    assert not {"read_range", "list_signals"} & set(hist.spy.used)  # no plant read here


def test_long_series_pass_through_as_histcraft_wrote_them(hist):
    """Series and batches are HistCraft's JSON bytes, never parsed and written again."""

    written = b'{"signal": "plc:FIC-101.PV",  "kind": "number", "t": [], "v": []}'
    batch = b'{"series": [],   "errors": []}'

    def handle(request: httpx.Request) -> httpx.Response:
        content = batch if request.method == "POST" else written
        return httpx.Response(200, content=content, headers={"content-type": "application/json"})

    rt = _rt(hist)
    rt.datalayer.http = httpx.Client(transport=httpx.MockTransport(handle))
    reader = _as(hist, "op")
    series = hist.get("/api/v1/signals/plc:FIC-101.PV/series", headers=reader)
    assert series.status_code == 200 and series.content == written
    assert series.headers["content-type"] == "application/json"
    answer = hist.post("/api/v1/series", json={"signals": ["plc:FIC-101.PV"]}, headers=reader)
    assert answer.status_code == 200 and answer.content == batch


def test_a_binary_batch_passes_through_when_the_caller_accepts_it(hist):
    """A caller that accepts the binary answer gets the Historian's bytes as they came; one
    that does not, or a Historian that answers JSON anyway, gets JSON."""

    from plantcraft_sdk import wire

    writer = wire.BinaryWriter()
    writer.numbers("plc:FIC-101.PV", "number", [1_760_000_000_000], [1.5])
    binary = writer.body([])
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.headers["accept"])
        if wire.MEDIA_TYPE in request.headers["accept"]:
            return httpx.Response(200, content=binary, headers={"content-type": wire.MEDIA_TYPE})
        return httpx.Response(200, content=b'{"series": [], "errors": []}')

    _rt(hist).datalayer.http = httpx.Client(transport=httpx.MockTransport(handle))
    reader = _as(hist, "op")
    body = {"signals": ["plc:FIC-101.PV"]}
    accept = {**reader, "Accept": f"{wire.MEDIA_TYPE}, application/json;q=0.5"}
    answer = hist.post("/api/v1/series", json=body, headers=accept)
    assert answer.content == binary
    assert answer.headers["content-type"].startswith(wire.MEDIA_TYPE)
    assert wire.read_binary(answer.content)[0][0]["v"].tolist() == [1.5]
    plain = hist.post("/api/v1/series", json=body, headers=reader)
    assert plain.headers["content-type"] == "application/json"
    assert wire.MEDIA_TYPE in asked[0] and wire.MEDIA_TYPE not in asked[1]


def test_callers_are_checked_before_anything_is_forwarded(hist):
    assert hist.get("/api/v1/signals").status_code == 401
    assert hist.get("/api/v1/signals", headers=_as(hist, "wall")).status_code == 403
    assert hist.put("/api/v1/series", json=[], headers=_as(hist, "eng")).status_code == 403
    assert hist.fake.requests == []


@pytest.mark.parametrize(
    ("fail", "timeout", "status"),
    [
        (500, False, 502),
        (503, False, 502),
        (401, False, 502),
        (404, False, 404),
        (422, False, 422),
        # A read past the Historian's time limit (HISTCRAFT_QUERY_TIMEOUT): its advice reaches
        # the caller.
        (504, False, 504),
        (None, True, 504),
    ],
)
def test_histcraft_failures_map_to_v1_statuses(hist, fail, timeout, status):
    hist.fake.fail, hist.fake.timeout = fail, timeout
    reader = _as(hist, "op")
    for method, path in (
        ("GET", "/api/v1/signals"),
        ("GET", "/api/v1/signals/plc:FIC-101.PV/series"),
        ("GET", "/api/v1/signals/plc:FIC-101.PV/value"),
    ):
        answer = hist.request(method, path, headers=reader)
        assert answer.status_code == status, (path, answer.text)
        assert answer.json()["detail"]
    answer = hist.post("/api/v1/series", json={"signals": ["x"]}, headers=reader)
    assert answer.status_code == status


def test_a_rejected_token_is_renewed_once(hist):
    fake, reader = hist.fake, _as(hist, "op")
    hist.get("/api/v1/signals", headers=reader)
    original = fake.handle
    seen = []

    def once(request):
        seen.append(request.headers["authorization"])
        if len(seen) == 1:
            return httpx.Response(401, json={"detail": "Unknown key."})
        return original(request)

    _rt(hist).datalayer.http = httpx.Client(transport=httpx.MockTransport(once))
    _rt(hist).datalayer._token = ("stale", 1e12)
    assert hist.get("/api/v1/signals", headers=reader).status_code == 200
    assert seen[0] == "Bearer stale" and seen[1] != seen[0]


def test_derived_writes_are_forwarded_with_the_app(hist):
    body = [
        {
            "signal": "app-linkcraft:health.fic-101",
            "t": ["2026-10-19T06:00:00Z"],
            "v": [80],
            "unit": "/100",
        }
    ]
    answer = hist.put("/api/v1/series", json=body, headers=_service(hist))
    assert answer.status_code == 200 and answer.json() == {"written": 1, "errors": []}
    [call] = hist.fake.calls("POST", "/derived")
    [item] = call["body"]["series"]
    assert item["app"] == "linkcraft" and item["signal"] == "app-linkcraft:health.fic-101"
    assert (
        item["t"] == ["2026-10-19T06:00:00+00:00"]
        and item["v"] == [80.0]
        and item["kind"] == "number"
    )
    assert _rt(hist).platform.derived.signals() == []  # nothing kept here
    two = [
        {**body[0], "signal": "app-linkcraft:ok"},
        {**body[0], "signal": "app-linkcraft:refused"},
    ]
    answer = hist.put("/api/v1/series", json=two, headers=_service(hist)).json()
    assert answer["written"] == 1
    assert answer["errors"] == [
        {"index": 1, "signal": "app-linkcraft:refused", "status": 403, "detail": "Not yours."}
    ]
    foreign = [{**body[0], "signal": "app-histcraft:x"}]
    assert hist.put("/api/v1/series", json=foreign, headers=_service(hist)).status_code == 403
    assert len(hist.fake.calls("POST", "/derived")) == 2


def test_typed_points_and_runs_are_forwarded_as_the_historian_takes_them(hist):
    typed = {
        "signal": "app-linkcraft:fic-101.daily.flags",
        "kind": "structured",
        "t": ["2026-10-19T06:00:00Z"],
        "v": [{"stiction": True}],
        "retention_days": 0,
        "managed_by": "link:daily",
    }
    assert hist.put("/api/v1/series", json=[typed], headers=_service(hist)).status_code == 200
    [item] = hist.fake.calls("POST", "/derived")[0]["body"]["series"]
    assert (item["kind"], item["v"], item["retention_days"], item["managed_by"]) == (
        "structured",
        [{"stiction": True}],
        0,
        "link:daily",
    )
    run = {
        "signal": "app-linkcraft:fic-101.daily.forecast",
        "run_at": "2026-10-19T00:00:00Z",
        "t": ["2026-10-19T01:00:00Z"],
        "v": [1],
        "keep_runs": 3,
    }
    answer = hist.put("/api/v1/series/runs", json=[run], headers=_service(hist))
    assert answer.json() == {"written": 1, "errors": []}
    [call] = hist.fake.calls("POST", "/derived/runs")
    assert call["body"]["app"] == "linkcraft"
    assert call["body"]["series"][0]["run_at"] == "2026-10-19T00:00:00+00:00"
    assert call["body"]["series"][0]["keep_runs"] == 3
    reader = _as(hist, "op")
    url = f"/api/v1/signals/{SIGNAL['id']}/series"
    runs = hist.get(url, params={"runs": 3}, headers=reader).json()
    assert runs["kind"] == "runs" and runs["runs"][0]["run_at"].startswith("2026-10-19")
    [read] = [item for item in hist.fake.calls("GET") if item["path"].endswith("/series")]
    assert read["query"] == {"runs": "3"}
    listed = hist.get(f"/api/v1/signals/{SIGNAL['id']}/runs", headers=reader).json()
    assert listed["runs"][0]["run_at"].startswith("2026-10-19")
    assert hist.fake.calls("GET")[-1]["query"] == {"limit": "50"}


def test_retired_derived_series_are_retired_in_histcraft(hist):
    body = {"signals": ["app-linkcraft:fic-101.status", "app-linkcraft:gone"]}
    answer = hist.post("/api/v1/series/retire", json=body, headers=_service(hist))
    assert answer.status_code == 200
    assert answer.json() == {"retired": ["app-linkcraft:fic-101.status"], "errors": []}
    calls = hist.fake.calls("DELETE")
    assert [call["path"] for call in calls] == [f"/signals/{item}" for item in body["signals"]]
    foreign = {"signals": ["app-histcraft:x"]}
    assert (
        hist.post("/api/v1/series/retire", json=foreign, headers=_service(hist)).status_code == 403
    )
    assert len(hist.fake.calls("DELETE")) == 2


def test_result_subjects_are_signals_histcraft_knows(hist):
    headers = _service(hist)
    results = [
        {"subject": "signal:plc:FIC-101.PV", "kind": "loop_health", "status": "ok"},
        {"subject": "signal:plc:missing", "kind": "loop_health", "status": "ok"},
        {"subject": "signal:FIC-101.PV", "kind": "valve", "status": "ok"},
    ]
    answer = hist.put("/api/v1/results", json=results, headers=headers).json()
    assert answer["saved"] == 2 and answer["errors"][0]["status"] == 404
    listed = hist.get("/api/v1/results", params={"kind": "valve"}, headers=headers).json()
    assert [item["subject"] for item in listed] == ["signal:plc:FIC-101.PV"]  # canonical id


def test_sources_are_managed_in_histcraft(hist):
    fake = hist.fake
    _admin(hist)
    listed = hist.get("/api/data/sources").json()
    assert [(s["source_id"], s["type"], s["origin"]) for s in listed] == [
        ("plc", "opcua", "histcraft")
    ]
    [plc] = listed
    assert plc["endpoint"] == "opc.tcp://plc:4840/" and plc["has_password"] is True
    assert plc["settings"]["endpoint_url"] == "opc.tcp://plc:4840/"
    assert (
        plc["settings"]["namespace_uri"] == "urn:plc" and plc["settings"]["timeout_seconds"] == 10
    )
    assert "never-shown" not in json.dumps(listed)
    settings = {
        "base_url": "https://pi.example/piwebapi",
        "server": "PI01",
        "auth_type": "basic",
        "username": "svc",
        "tags": "A\nB",
        "history_cache_hours": 0,
    }
    created = hist.post(
        "/api/data/sources",
        json={"name": "PI", "type": "pi_web_api", "settings": settings, "password": "s3cret"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["source_id"] == "pi" and created.json()["configured_tags"] == 2
    [call] = fake.calls("POST", "/sources")
    sent = call["body"]
    assert (sent["id"], sent["name"], sent["kind"], sent["password"]) == (
        "pi",
        "PI",
        "pi_web_api",
        "s3cret",
    )
    assert sent["endpoint"] == "https://pi.example/piwebapi" and sent["username"] == "svc"
    assert sent["signals"] == ["A", "B"]
    assert sent["options"]["server"] == "PI01" and sent["options"]["auth_type"] == "basic"
    assert sent["options"]["timezone"] and "history_cache_hours" not in sent["options"]
    assert "password" not in created.json()["settings"]
    again = hist.post(
        "/api/data/sources", json={"name": "PI", "type": "pi_web_api", "settings": settings}
    )
    assert again.status_code == 409
    bad = hist.post("/api/data/sources", json={"name": "X", "type": "opcua", "settings": {}})
    assert bad.status_code == 422  # checked here, never sent
    edited = hist.put(
        "/api/data/sources/pi", json={"name": "PI 2", "type": "pi_web_api", "settings": settings}
    )
    assert edited.status_code == 200, edited.text
    put = fake.calls("PUT", "/sources/pi")[0]["body"]
    assert put["password"] is None and "signals" not in put  # the stored password is kept
    used = hist.post("/api/data/sources/pi/signals/use", json={"tags": ["C", "D"]})
    assert used.json() == {"updated": 2, "kept_by_scenario": []}
    assert fake.calls("POST", "/sources/pi/signals")[0]["body"] == {"signals": ["C", "D"]}
    status = hist.get("/api/data/sources/plc/status").json()
    assert status["ok"] is True and "PLC 1.0" in status["message"]
    failing = hist.get("/api/data/sources/pi/status").json()
    assert failing["ok"] is False and "refused basic" in failing["message"]
    plc_settings = {"endpoint_url": "opc.tcp://plc:4840/", "namespace_uri": "urn:plc"}
    tested = hist.post(
        "/api/data/sources/test",
        json={"type": "opcua", "settings": plc_settings, "source_id": "plc"},
    ).json()
    assert tested["ok"] is True and "opc.tcp://plc:4840/" in tested["message"]
    no_settings = {"type": "opcua", "settings": {}, "source_id": "plc"}
    assert hist.post("/api/data/sources/test", json=no_settings).status_code == 422
    page = hist.get(
        "/api/data/sources/plc/signals", params={"q": "Unit", "offset": 2, "limit": 3}
    ).json()
    assert [item["tag"] for item in page["items"]] == ["V2", "V3", "V4"] and page["total"] == 5
    assert page["items"][0]["read_from"] == "plc" and page["items"][0]["path"] == "Unit"
    assert fake.calls("POST", "/sources/plc/browse")[0]["body"] == {"limit": 5, "root": "Unit"}
    unsaved = hist.post(
        "/api/data/sources/test", json={"type": "pi_web_api", "settings": settings}
    ).json()
    assert unsaved["ok"] is True and "https://pi.example/piwebapi" in unsaved["message"]
    sent = fake.calls("POST", "/sources/test")[-1]["body"]
    assert sent["kind"] == "pi_web_api" and sent["options"]["server"] == "PI01"
    assert sent["password"] == ""  # a new source has no stored password to fall back on
    editing = hist.post(
        "/api/data/sources/test",
        json={"type": "pi_web_api", "settings": settings, "source_id": "pi"},
    ).json()
    assert editing["ok"] is True
    sent = fake.calls("POST", "/sources/test")[-1]["body"]
    assert sent["id"] == "pi" and sent["password"] is None  # HistCraft uses the stored one
    down = {**settings, "base_url": "https://down.example/piwebapi"}
    failed = hist.post("/api/data/sources/test", json={"type": "pi_web_api", "settings": down})
    assert failed.status_code == 200 and failed.json()["ok"] is False
    assert "Host down" in failed.json()["message"]
    stopped = hist.post(
        "/api/data/sources/plc/signals/use", json={"tags": ["X", "gone"], "monitored": False}
    )
    assert stopped.json() == {"updated": 1, "kept_by_scenario": []}  # never used: skipped
    patches = fake.calls("PATCH")
    assert [(c["path"], c["body"]) for c in patches] == [
        ("/signals/plc:X", {"enabled": False}),
        ("/signals/plc:gone", {"enabled": False}),
    ]
    with pytest.raises(DataLayerError) as refused:
        _rt(hist).datalayer.stop_signals("app", ["linkcraft:x"])
    assert refused.value.status == 422  # derived signals: HistCraft's refusal is passed on
    assert hist.delete("/api/data/sources/pi").json() == {"removed": "pi", "signals": 0}
    assert hist.delete("/api/data/sources/plc").status_code == 409  # it still has signals
    assert hist.delete("/api/data/sources/nope").status_code == 404
    assert _rt(hist).platform.sources.store.sources() == []  # nothing kept here
    assert not {"read_range", "list_signals", "test_connection"} & set(hist.spy.used)


def test_the_interface_charts_read_through_histcraft(hist):
    _admin(hist)
    history = hist.get("/api/data/history", params={"tag": "plc:FIC-101.PV", "hours": 2})
    assert history.status_code == 200, history.text
    assert list(history.json()["series"]) == ["plc:FIC-101.PV"]
    assert history.json()["series"]["plc:FIC-101.PV"][0][1] == 1.5
    series = hist.get("/api/signals/plc:FIC-101.PV/series", params={"window": "1h"})
    assert series.status_code == 200 and series.json()["series"][0][1] == 1.5
    value = hist.get("/api/signals/plc:FIC-101.PV/value", params={"window": "1h"}).json()
    assert value["value"] == 1.5
    hist.fake.timeout = True
    assert hist.get("/api/signals/plc:FIC-101.PV/value").status_code == 504
    assert not {"read_range"} & set(hist.spy.used)


def test_an_opcua_source_sends_only_the_options_histcraft_takes():
    """The demo map's OPC UA source carries auth_type: HistCraft refuses it ("Unknown option")."""

    from plantcraft.platform.datalayer.histcraft import source_body

    settings = {
        "endpoint_url": "opc.tcp://plantcraft:4840/plantcraft/",
        "namespace_uri": "urn:processcraft:plantcraft",
        "auth_type": "anonymous",
        "timeout_seconds": 30.0,
        "server": "ignored",
    }
    body = source_body(
        "plantcraft", name="Simulator", type="opcua", settings=settings, password=None
    )
    assert body["options"] == {"timeout_seconds": 30.0}
    assert body["namespace_uri"] == "urn:processcraft:plantcraft"
    csv = source_body(
        "f",
        name="F",
        type="csv",
        settings={"path": "x.csv", "auth_type": "basic", "timezone": "UTC"},
        password=None,
    )
    assert csv["options"] == {"timezone": "UTC"}


def test_the_demo_map_imports_into_histcraft(hist):
    """install.sh --demo: the Simulator map creates the source and its signals in HistCraft."""

    _admin(hist)
    plant = {
        "sources": [
            {
                "source_id": "plantcraft",
                "name": "Simulator",
                "type": "opcua",
                "endpoint_url": "opc.tcp://plantcraft:4840/plantcraft/",
                "namespace_uri": "urn:processcraft:plantcraft",
                "auth_type": "anonymous",
            }
        ],
        "assets": [{"asset_id": "U-SIM", "name": "Simulated unit", "kind": "unit"}],
        "signals": [
            {"tag": "CPM.Loops.FIC-1003.PV", "source_id": "plantcraft", "name": "FIC-1003 PV"},
            {"tag": "CPM.Loops.FIC-1003.OP", "source_id": "plantcraft", "name": "FIC-1003 OP"},
        ],
        "loops": [
            {
                "loop_id": "FIC-1003",
                "name": "Recycle flow",
                "area": "Recycle",
                "unit": "U-SIM",
                "pv": "CPM.Loops.FIC-1003.PV",
                "op": "CPM.Loops.FIC-1003.OP",
                "loop_type": "flow",
            }
        ],
    }
    answer = hist.post("/api/map/apply?filename=plant.json", content=json.dumps(plant).encode())
    assert answer.status_code == 200, answer.text
    [created] = hist.fake.calls("POST", "/sources")
    assert created["body"]["id"] == "plantcraft" and "auth_type" not in created["body"]["options"]
    added = [
        call["body"]["signals"] for call in hist.fake.calls("POST", "/sources/plantcraft/signals")
    ]
    assert len(added) == 1  # one call for the whole source
    assert sorted(tag for batch in added for tag in batch) == [
        "CPM.Loops.FIC-1003.OP",
        "CPM.Loops.FIC-1003.PV",
    ]
    assert _rt(hist).platform.sources.store.sources() == []  # nothing kept here
    bound = {
        item["role"]: item["source_id"] for item in _rt(hist).workspace.assets.signals("FIC-1003")
    }
    assert bound == {"pv": "plantcraft", "op": "plantcraft"}  # not the scenario's source
    # A loop bound before HistCraft (no source) is bound again by the next import.
    store = _rt(hist).workspace.assets
    store.set_signals(
        "FIC-1003",
        [
            {"signal_id": "CPM.Loops.FIC-1003.PV", "role": "pv"},
            {"signal_id": "CPM.Loops.FIC-1003.OP", "role": "op"},
        ],
        origin="map",
    )
    again = hist.post("/api/map/apply?filename=plant.json", content=json.dumps(plant).encode())
    assert again.status_code == 200, again.text
    assert {item["source_id"] for item in store.signals("FIC-1003")} == {"plantcraft"}


def test_a_map_may_name_a_source_kept_in_histcraft(hist):
    """A signals sheet without a sources sheet: the source exists in HistCraft (added on its
    pages or by an earlier import) and is known, read once for the whole file."""

    _admin(hist)
    plant = {
        "assets": [{"asset_id": "TIC-777", "name": "Reactor temperature", "kind": "loop"}],
        "signals": [
            {
                "tag": f"TIC-777.{role.upper()}",
                "source_id": "plc",
                "asset_id": "TIC-777",
                "role": role,
            }
            for role in ("pv", "sp", "op")
        ],
    }
    preview = hist.post("/api/map/preview?filename=plant.json", content=json.dumps(plant).encode())
    assert preview.status_code == 200, preview.text
    assert not [i for i in preview.json()["issues"] if i["level"] == "error"], preview.text
    assert len(hist.fake.calls("GET", "/sources")) == 1
    answer = hist.post("/api/map/apply?filename=plant.json", content=json.dumps(plant).encode())
    assert answer.status_code == 200 and answer.json()["applied"], answer.text
    roles = {
        item["role"]: item["source_id"] for item in _rt(hist).workspace.assets.signals("TIC-777")
    }
    assert roles == {"pv": "plc", "sp": "plc", "op": "plc"}
    # A source neither in the file nor in HistCraft is still an error.
    plant["signals"][0]["source_id"] = "nowhere"
    wrong = hist.post("/api/map/preview?filename=plant.json", content=json.dumps(plant).encode())
    assert any("nowhere" in i["message"] for i in wrong.json()["issues"])
