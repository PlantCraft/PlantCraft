"""Layers inside PlantCraft Simulator only import downward (AGENTS.md, section 2)."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "simcraft"

# Layer of each module (dotted name below `simcraft`). A module may import its own layer or
# lower ones. The benchmark and the loop portfolio share only `contracts` (the namespace URI)
# and `settings`; neither imports the other's modules.
LAYERS: dict[str, int] = {
    "settings": 0,
    "catalog": 1,
    "profiles": 1,
    "model": 2,
    "engine": 3,
    "contracts": 3,
    "storage": 3,
    "dataset": 4,
    "experiments": 4,
    "server": 4,
    "loops.faults": 1,
    "loops.dynamics": 1,
    "loops.storage": 2,
    "loops.server": 4,
    "loops.control": 4,
    "loops": 4,
    # The source test kit (development and CI only) reads the benchmark's engine.
    "testkit.plant": 4,
    "testkit.background": 4,
    "testkit.csv_files": 5,
    "testkit.piwebapi": 5,
    "testkit.mqtt": 5,
    "testkit.modbus": 5,
    "testkit.sql": 5,
    "testkit.cli": 5,
    "testkit": 5,
    "healthcheck": 5,
    "cli": 6,
    "__main__": 7,
    "": 7,
}
BENCHMARK_ONLY = {"catalog", "profiles", "model", "engine", "storage", "dataset", "experiments"}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parts = module.split(".") if module else []
    package = parts if path.name == "__init__.py" else parts[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                target = ".".join([*base, *(node.module.split(".") if node.module else [])])
            elif node.module and node.module.startswith("simcraft"):
                target = node.module.removeprefix("simcraft").lstrip(".")
            else:
                continue
            found.add(target)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("simcraft."):
                    found.add(alias.name.removeprefix("simcraft."))
    return found


def test_every_module_has_a_layer() -> None:
    modules = {_module_name(path) for path in PACKAGE.rglob("*.py")}
    assert modules == set(LAYERS)


def test_imports_only_go_down_and_the_two_simulators_stay_apart() -> None:
    violations = []
    for path in PACKAGE.rglob("*.py"):
        module = _module_name(path)
        for target in _imports(path, module):
            if target not in LAYERS:
                continue
            if LAYERS[target] > LAYERS[module]:
                violations.append(f"{module} -> {target} (layer up)")
            if module.startswith("loops") and target in BENCHMARK_ONLY:
                violations.append(f"{module} -> {target} (loops use benchmark code)")
    assert violations == []
