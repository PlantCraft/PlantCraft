# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""llm-egress, the suite's one way out to a language model in the cloud (processcraft/egress):
PlantCraft lists the providers' hosts, the proxy opens a tunnel to those on 443 and nothing else."""

from __future__ import annotations

import asyncio
import json

import pytest

from processcraft import egress
from tests.test_collaboration import signed  # noqa: F401

PUBLIC = "93.184.216.34"


def test_public_hosts_go_through_the_proxy_and_plant_hosts_do_not(monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_LLM_PROXY", "http://llm-egress:3128")
    assert (
        egress.proxy_for("https://api.openai.com/v1/chat/completions") == "http://llm-egress:3128"
    )
    for url in (
        "http://api.openai.com/v1",  # only HTTPS goes out
        "https://llm.plant.local:11434/v1",
        "https://10.20.0.7/v1",
        "https://localhost:8000/v1",
        "https://ollama:11434/v1",
    ):
        assert egress.proxy_for(url) == "", url
    monkeypatch.setenv("PLANTCRAFT_LLM_NO_PROXY", "llm.example.com")
    assert egress.proxy_for("https://llm.example.com/v1") == ""
    monkeypatch.delenv("PLANTCRAFT_LLM_PROXY")
    assert egress.proxy_for("https://api.openai.com/v1") == ""


def test_the_list_keeps_only_internet_hosts_and_a_broken_file_opens_nothing(tmp_path):
    path = tmp_path / "egress" / "allow.json"
    assert egress.read_allowlist(path) == set()
    assert egress.write_allowlist(["API.openai.com", "llm.plant.local", "10.0.0.5", ""], path)
    assert egress.read_allowlist(path) == {"api.openai.com"}
    path.write_text("{not json")
    assert egress.read_allowlist(path) == set()
    assert egress.provider_host("openai", "") == "api.openai.com"
    assert egress.provider_host("openai", "https://gw.example.com/v1") == "gw.example.com"


class _Echo:
    """A stand-in for the model service: echoes what it receives."""

    async def __aenter__(self):
        async def echo(reader, writer):
            writer.write(await reader.read(100))
            await writer.drain()
            writer.close()

        self.server = await asyncio.start_server(echo, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()


async def _ask(gate: egress.Gate, request: bytes, then: bytes = b"") -> bytes:
    server = await asyncio.start_server(gate.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request)
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        body = b""
        if then and head.startswith(b"HTTP/1.1 200"):
            writer.write(then)
            await writer.drain()
        body = await asyncio.wait_for(reader.read(4096), 5)
        writer.close()
        return head + body
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture()
def listed(tmp_path):
    path = tmp_path / "allow.json"
    egress.write_allowlist(["api.openai.com"], path)
    return path


def test_the_gate_opens_a_tunnel_to_a_listed_host_only(listed):
    async def run():
        async with _Echo() as upstream:
            dialed = []

            async def resolve(host, port):
                return {"api.openai.com": [PUBLIC], "inside.example.com": ["10.1.2.3"]}[host]

            async def open_connection(address, port):
                dialed.append((address, port))
                return await asyncio.open_connection("127.0.0.1", upstream.port)

            gate = egress.Gate(listed, resolve=resolve, open_connection=open_connection)
            opened = await _ask(gate, b"CONNECT api.openai.com:443 HTTP/1.1\r\n\r\n", b"hello")
            assert opened.startswith(b"HTTP/1.1 200") and opened.endswith(b"hello")
            assert dialed == [(PUBLIC, 443)]
            refused = await _ask(gate, b"CONNECT github.com:443 HTTP/1.1\r\n\r\n")
            assert refused.startswith(b"HTTP/1.1 403") and b"Settings" in refused
            assert (await _ask(gate, b"CONNECT api.openai.com:80 HTTP/1.1\r\n\r\n")).startswith(
                b"HTTP/1.1 403"
            )
            assert (await _ask(gate, b"GET http://api.openai.com/ HTTP/1.1\r\n\r\n")).startswith(
                b"HTTP/1.1 405"
            )
            egress.write_allowlist(["api.openai.com", "inside.example.com"], listed)
            inside = await _ask(gate, b"CONNECT inside.example.com:443 HTTP/1.1\r\n\r\n")
            assert inside.startswith(b"HTTP/1.1 403") and b"inside the plant" in inside
            assert dialed == [(PUBLIC, 443)]
            status = await _ask(gate, b"GET /status HTTP/1.1\r\n\r\n")
            seen = json.loads(status.split(b"\r\n\r\n", 1)[1])
            assert seen["opened"] == 1 and seen["refused"] == 3
            assert seen["hosts"] == ["api.openai.com", "inside.example.com"]
            assert seen["recent"][0]["host"] == "inside.example.com"

    asyncio.run(run())


def test_no_list_means_every_connection_is_refused(tmp_path):
    gate = egress.Gate(tmp_path / "missing.json")
    answer = asyncio.run(_ask(gate, b"CONNECT api.openai.com:443 HTTP/1.1\r\n\r\n"))
    assert answer.startswith(b"HTTP/1.1 403")


def test_plantcraft_lists_the_hosts_of_its_providers(signed, tmp_path, monkeypatch):
    path = tmp_path / "egress" / "allow.json"
    monkeypatch.setenv("PLANTCRAFT_EGRESS_ALLOWLIST", str(path))
    signed.post(
        "/api/language-models/providers",
        json={
            "name": "OpenAI",
            "kind": "openai",
            "endpoint": "https://openai.com",
            "models": ["m"],
        },
    )
    signed.post(
        "/api/language-models/providers",
        json={
            "name": "Ollama",
            "kind": "openai",
            "endpoint": "http://llm.plant.local:11434/v1",
            "models": ["llama3.1:70b"],
        },
    )
    assert egress.read_allowlist(path) == {"api.openai.com"}
    seen = signed.get("/api/language-models").json()["egress"]
    assert seen["hosts"] == ["api.openai.com"] and seen["configured"] is False
    store = signed.app.state.runtime.specialists
    monkeypatch.setenv("PLANTCRAFT_LLM", "off")
    store.sync_egress()
    assert egress.read_allowlist(path) == set()
