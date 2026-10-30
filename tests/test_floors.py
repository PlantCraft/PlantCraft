"""Measured numbers never drop below the floors in tests/floors.toml."""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOORS = tomllib.loads((ROOT / "tests" / "floors.toml").read_text(encoding="utf-8"))


def _catalog_size(path: Path) -> int:
    return len(json.loads(path.read_text(encoding="utf-8")))


def _app(tmp_path, monkeypatch):
    from plantcraft.api.app import create_app
    from plantcraft.api.runtime import ApiRuntime

    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    return create_app(ApiRuntime.from_environment())


def _tests_in(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def test_api_floors(tmp_path, monkeypatch):
    from tests.test_hostile_inputs import _api_routes

    routes = _api_routes(_app(tmp_path, monkeypatch))
    assert len(routes) >= FLOORS["api"]["operations"]
    v1 = [route for route in routes if route[1].startswith("/api/v1/")]
    assert len(v1) >= FLOORS["api"]["v1_operations"]


def test_contract_floor():
    count = sum(_tests_in(path) for path in (ROOT / "tests" / "contract").glob("test_*.py"))
    assert count >= FLOORS["api"]["contract_tests"]


def test_source_type_floor():
    from plantcraft.industrial_data.registry import SOURCE_TYPES

    assert len(SOURCE_TYPES) >= FLOORS["sources"]["types"]


def test_e2e_journey_floor():
    count = sum(_tests_in(path) for path in (ROOT / "tests" / "e2e").glob("test_*.py"))
    assert count >= FLOORS["e2e"]["journeys"]


def test_translation_floors():
    frontend = _catalog_size(ROOT / "frontend" / "src" / "locales" / "pt-BR.json")
    backend = _catalog_size(ROOT / "plantcraft" / "i18n" / "locales" / "pt-BR.json")
    assert frontend >= FLOORS["i18n"]["frontend_pt_br"]
    assert backend >= FLOORS["i18n"]["backend_pt_br"]
