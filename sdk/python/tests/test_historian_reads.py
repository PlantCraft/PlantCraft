"""Signal and series reads straight from the Historian (``historian_url``, SDK 0.13.0).

The Historian serves API v1's read routes itself (``/api/v1/reads``); here the fake answers
them under ``/hist`` on its own host, so each test sees which host every request went to.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from plantcraft_sdk import client as client_module
from plantcraft_sdk.client import NotFound, PlantCraftClient, Unavailable
from plantcraft_sdk.testing import BASE_URL, FakePlantCraft

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
HOUR = NOW - timedelta(hours=1)
HISTORIAN = "http://histcraft.test/hist"


class Stack:
    """PlantCraft (the fake) and a Historian serving the same reads; ``down`` cuts it off."""

    def __init__(self, *, reads: bool = True, status: int | None = None):
        self.fake = FakePlantCraft(now=NOW)
        self.reads = reads
        self.status = status
        self.down = False
        self.hosts: list[tuple[str, str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        self.hosts.append((host, request.method, path))
        if host != "histcraft.test":
            return self.fake._httpx(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if self.status is not None:
            return httpx.Response(self.status, json={"detail": "The plant source did not answer."})
        path = path.removeprefix("/hist")
        if path == "/api/v1/reads":
            if not self.reads:
                return httpx.Response(404, json={"detail": "Not Found"})
            return httpx.Response(200, json={"api": 1})
        forwarded = httpx.Request(
            request.method,
            BASE_URL + path + "?" + request.url.query.decode(),
            headers=request.headers,
            content=request.read(),
        )
        return self.fake._httpx(forwarded)

    def client(self, **options) -> PlantCraftClient:
        http = httpx.Client(transport=httpx.MockTransport(self))
        token = self.fake.token("engineer")
        return PlantCraftClient(
            BASE_URL, token, http_client=http, retries=0, historian_url=HISTORIAN, **options
        )

    def where(self) -> list[str]:
        hosts, self.hosts = [host for host, _, _ in self.hosts], []
        return hosts


def test_reads_go_to_the_historian_the_rest_to_processcraft():
    stack = Stack()
    client = stack.client()
    single = client.series("fake:FIC-101.PV", HOUR, NOW)
    assert stack.hosts[0] == ("histcraft.test", "GET", "/hist/api/v1/reads")  # asked once
    assert stack.where() == ["histcraft.test", "histcraft.test"]
    batch = client.series_many(["fake:FIC-101.PV", "NOPE"], HOUR, NOW)
    assert batch["series"][0] == single and batch["errors"][0]["status"] == 404
    client.signal("fake:FIC-101.PV")
    client.signals("FIC")
    client.value("fake:FIC-101.PV", "mean", "1h")
    assert stack.where() == ["histcraft.test"] * 4
    client.assets()
    client.audit("checked", "asset:fic-101")
    assert stack.where() == ["processcraft.test"] * 2
    # a person's client made from a service client shares what the probe found
    client.with_token(stack.fake.token("operator")).series("fake:FIC-101.PV", HOUR, NOW)
    assert stack.where() == ["histcraft.test"]


def test_the_historian_answers_as_processcraft_would():
    stack = Stack()
    direct = stack.client().series_many(["fake:LIC-102.PV"], HOUR, NOW, 60)
    stack.where()
    through = stack.fake.client("engineer").series_many(["fake:LIC-102.PV"], HOUR, NOW, 60)
    assert direct == through
    with pytest.raises(NotFound):
        stack.client().series("NOPE", HOUR, NOW)
    assert "processcraft.test" not in stack.where()


def test_a_historian_that_cannot_be_reached_leaves_reads_to_processcraft(monkeypatch):
    stack = Stack()
    client = stack.client()
    client.series("fake:FIC-101.PV", HOUR, NOW)
    stack.where()
    stack.down = True
    client.series("fake:FIC-101.PV", HOUR, NOW)
    assert stack.where() == ["histcraft.test", "processcraft.test"]
    # for a while it is not tried at all
    client.series_many(["fake:FIC-101.PV"], HOUR, NOW)
    assert stack.where() == ["processcraft.test"]
    # then asked again
    stack.down = False
    monkeypatch.setattr(client._historian, "until", 0.0)
    client.series("fake:FIC-101.PV", HOUR, NOW)
    assert stack.where() == ["histcraft.test", "histcraft.test"]


def test_an_older_historian_without_reads():
    stack = Stack(reads=False)
    client = stack.client()
    client.series("fake:FIC-101.PV", HOUR, NOW)
    client.series("fake:FIC-101.PV", HOUR, NOW)
    assert stack.where() == ["histcraft.test", "processcraft.test", "processcraft.test"]


def test_a_failed_plant_source_is_the_answer_not_a_reason_to_ask_processcraft():
    stack = Stack()
    client = stack.client()
    client.series("fake:FIC-101.PV", HOUR, NOW)
    stack.where()
    stack.status = 502
    with pytest.raises(Unavailable) as failed:
        client.series("fake:FIC-101.PV", HOUR, NOW)
    assert failed.value.status_code == 502
    assert stack.where() == ["histcraft.test"]


def test_the_historian_url_comes_from_the_environment(monkeypatch):
    stack = Stack()
    http = httpx.Client(transport=httpx.MockTransport(stack))
    token = stack.fake.token("engineer")
    monkeypatch.setenv(client_module.HISTORIAN_URL_ENV, HISTORIAN + "/")
    PlantCraftClient(BASE_URL, token, http_client=http).series("fake:FIC-101.PV", HOUR, NOW)
    assert stack.where() == ["histcraft.test", "histcraft.test"]
    monkeypatch.setenv(client_module.HISTORIAN_URL_ENV, "")
    PlantCraftClient(BASE_URL, token, http_client=http).series("fake:FIC-101.PV", HOUR, NOW)
    assert stack.where() == ["processcraft.test"]
    # given as "" it is off whatever the environment says
    monkeypatch.setenv(client_module.HISTORIAN_URL_ENV, HISTORIAN)
    off = PlantCraftClient(BASE_URL, token, http_client=http, historian_url="")
    off.series("fake:FIC-101.PV", HOUR, NOW)
    assert stack.where() == ["processcraft.test"]
