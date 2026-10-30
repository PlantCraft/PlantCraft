"""Bad data never crashes: every API route, fed with junk.

An API route given absurd path values, query values or bodies answers 4xx,
never 500. (The method half of this test moved with the methods to CPMCraft,
which runs every registered method over hostile frames.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]


# API routes ---------------------------------------------------------------------

JUNK_SEGMENTS = [
    "x" * 300,
    "..%2F..%2Fetc%2Fpasswd",
    "%00",
    "'; DROP TABLE assets;--",
    "ç☃",
    "-1",
    "NaN",
]
JUNK_BODIES = [
    None,
    {},
    [],
    "not json",
    # JSON with non-finite numbers: a 422 that echoed them could not be encoded (G33).
    '{"start": NaN, "action": NaN, "name": Infinity, "kind": -Infinity}',
    {"name": None},
    {"name": "x" * 10_000},
    {"window": "-1d", "limit": -5},
]
PARAM = re.compile(r"\{[^}]+\}")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("hostile")
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    patch = pytest.MonkeyPatch()
    patch.setenv("PLANTCRAFT_SCENARIO", str(path))
    patch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    patch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    try:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as test_client:
            test_client.processcraft_app = app
            yield test_client
    finally:
        patch.undo()


def _api_routes(app) -> list[tuple[str, str]]:
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api/"):
            routes.extend((method.upper(), path) for method in sorted(operations))
    return routes


@pytest.mark.slow  # every route of the API, fed junk: about half a minute on purpose
def test_every_api_route_answers_junk_without_a_server_error(client):
    failures = []
    routes = _api_routes(client.processcraft_app)
    assert len(routes) > 40
    for method, path in routes:
        targets = (
            [PARAM.sub(segment, path) for segment in JUNK_SEGMENTS]
            if PARAM.search(path)
            else [path]
        )
        bodies = JUNK_BODIES if method in {"POST", "PUT", "PATCH"} else [None]
        for target in targets:
            for body in bodies:
                kwargs = {}
                if isinstance(body, str):
                    kwargs["content"] = body
                    kwargs["headers"] = {"Content-Type": "application/json"}
                elif body is not None:
                    kwargs["json"] = body
                response = client.request(
                    method, target, params={"window": "-1", "limit": "abc"}, **kwargs
                )
                if response.status_code >= 500:
                    failures.append(
                        f"{method} {target} body={str(body)[:40]!r} -> {response.status_code}"
                    )
    assert not failures, "\n".join(failures[:40])
