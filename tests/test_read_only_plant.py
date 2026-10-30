"""Read-only on plant systems (AGENTS.md, gap G10): PlantCraft never writes to PI or OPC UA.

Two locks: PI Web API goes through a session that refuses every verb but a read, and the code
that talks to plant systems never calls an OPC UA write, method call or node edit, nor an HTTP
write verb. A new plant-facing module is covered when it lands in ``PLANT_FACING``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plantcraft.industrial_data.pi_web_api import PiError, ReadOnlySession

ROOT = Path(__file__).resolve().parents[1] / "plantcraft"
# Modules that open connections to plant systems (PI Web API, OPC UA, CSV exports of them).
PLANT_FACING = [
    *sorted((ROOT / "industrial_data").glob("*.py")),
    ROOT / "platform" / "plantmap.py",
]
# asyncua calls that change a server: writes, method calls, node and reference edits.
OPCUA_WRITES = {
    "write_value",
    "write_values",
    "write_attribute",
    "write_attributes",
    "set_value",
    "set_attribute",
    "set_writable",
    "call_method",
    "add_nodes",
    "add_references",
    "delete_nodes",
    "delete_references",
    "add_variable",
    "add_object",
    "add_method",
    "history_update",
}
HTTP_WRITES = {"post", "put", "patch", "delete"}


@pytest.mark.parametrize("verb", ["POST", "PUT", "PATCH", "DELETE", b"POST"])
def test_the_pi_session_refuses_every_write(verb):
    with ReadOnlySession() as session, pytest.raises(PiError, match="only reads from PI"):
        session.request(verb, "https://pi.invalid/piwebapi/streams/x/value", json={"Value": 1})


def test_the_pi_session_still_reads(monkeypatch):
    sent: list[str] = []

    def adapter_send(_self, request, **_kwargs):
        sent.append(request.method)
        raise ConnectionError("no network in tests")

    monkeypatch.setattr("requests.adapters.HTTPAdapter.send", adapter_send)
    with ReadOnlySession() as session, pytest.raises(ConnectionError):
        session.get("https://pi.invalid/piwebapi/")
    assert sent == ["GET"]


def test_the_pi_client_uses_the_read_only_session():
    from plantcraft.config import DataSourceConfig
    from plantcraft.industrial_data.pi_web_api import PiWebApiSource

    config = DataSourceConfig(
        type="pi_web_api",
        server="pi-archive",
        base_url="https://pi.invalid/piwebapi",
        auth_type="basic",
        username="svc",
        password_env="HOME",
        tags=["X"],
    )
    source = PiWebApiSource(config)
    assert isinstance(source._session(), ReadOnlySession)


def _calls(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.func.attr, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]


def _speaks_http(path: Path) -> bool:
    # HTTP write verbs count only where an HTTP client is imported (a store's ``delete`` is not one).
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return bool(names & {"requests", "httpx", "urllib3", "aiohttp"})


def test_plant_facing_code_never_writes():
    assert len(PLANT_FACING) > 3
    found = []
    for path in PLANT_FACING:
        http = _speaks_http(path)
        for name, line in _calls(path):
            if name in OPCUA_WRITES or (http and name in HTTP_WRITES):
                found.append(f"{path.relative_to(ROOT.parent)}:{line} .{name}()")
    assert not found, "plant-facing code calls a write:\n" + "\n".join(found)
