"""Modules only import from their own layer's package or from layers below."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "plantcraft"

LAYERS = {
    "db": 0,
    "config": 0,
    "i18n": -1,
    "refs": 0,
    # Files written whole or not at all, created with their final mode (standard library only).
    "files": 0,
    # Backup, restore and updates (docs/operations.md): standard library only, run by the
    # installer and its throwaway helper containers.
    "ops": 0,
    # llm-egress, the one way out to a language model in the cloud (standard library only).
    "egress": 0,
    # The package's old name as a door to this one (copied to processcraft/ in the images).
    "legacy": 0,
    "industrial_data": 1,
    "auth": 1,
    "assets": 1,
    "events": 1,
    # The central audit log (PlantCraft and the apps of the suite).
    "audit": 1,
    # Apps installed from PlantCraft: signed packages, the installer, the catalog.
    "apps": 1,
    # Results, runs and schedules the apps publish through API v1.
    "results": 1,
    # The compute workers and the queue of tasks the apps hand them (docs/compute.md).
    "compute": 1,
    # What the apps explain about their own objects (protocols, runs), read by specialists.
    "knowledge": 1,
    # Conversations (Messages) and follow-up actions (docs/collaboration.md).
    "messages": 1,
    "actions": 1,
    # What each person arranges for themselves (the widgets of their Overview).
    "preferences": 1,
    # The installation's own settings (Setup › Installation): its time zone.
    "installation": 1,
    # The suite's certificates and when they expire (Health).
    "certificates": 1,
    # AI assistant access: the MCP server's switch, people's access tokens, the read-only tools.
    "assistant_access": 1,
    # The assistant's works: what it does on each page, and the context of a chat started there.
    "assistant_works": 1,
    # Groups of people, shared by every app (docs/groups.md).
    "groups": 1,
    # Notebooks: the switch and the notebooks PlantCraft writes for each person (JupyterLite).
    "notebooks": 1,
    # The kernel: workspace, sources, asset tree, loops and the plant map.
    "platform": 2,
    # Specialists: robot users answering in Messages, reading what their apps publish.
    "specialists": 2,
    # The suite watch: "System" tells the admins in Messages when a part of the suite stops.
    "watch": 2,
    # Notifications the apps send to people and groups: Messages and email (docs/notifications.md).
    "notify": 2,
    # Desk, each person's day: to-dos, own events, followed assets, calendars (docs/desk.md).
    "desk": 2,
    # The assistant's chats in Desk: a person's own chats with a model and read-only tools.
    "assistant_chat": 2,
    # Corporate sign-in: LDAP or Active Directory and OIDC, their groups as access here.
    "directory": 2,
    "api": 3,
    "cli": 3,
    # The demo story: an HTTP client of the apps, run by `processcraft demo seed`.
    "demo_seed": 3,
}
# Packages that left for their own repositories; nothing here may come back to them.
MOVED = {
    "applications": "cpmcraft",
    "catalog": "cpmcraft (methods: plantcraft_sdk.methods)",
    "engine": "cpmcraft",
    "report": "cpmcraft",
    "work": "parked",
    "visualization": "trendcraft (later)",
    "demo": "cpmcraft (bench)",
    "simulator": "simcraft (`simcraft loops serve`)",
}
TOP = max(LAYERS.values())


def _module_of(path: Path) -> str:
    return path.relative_to(PACKAGE).parts[0].removesuffix(".py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        for name in names:
            parts = name.split(".")
            if parts[0] == "plantcraft" and len(parts) > 1:
                found.add(parts[1])
    return found


def test_every_module_has_a_layer():
    modules = {
        _module_of(path)
        for path in PACKAGE.rglob("*.py")
        if path.parent != PACKAGE or path.name != "__init__.py"
    }
    assert modules <= set(LAYERS), sorted(modules - set(LAYERS))


def test_dependencies_only_point_down():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        if path.parent == PACKAGE and path.name == "__init__.py":
            continue
        owner = _module_of(path)
        for target in _imports(path) - {owner}:
            owner_layer, target_layer = LAYERS[owner], LAYERS.get(target, -1)
            if target_layer > owner_layer or (target_layer == owner_layer and owner_layer != TOP):
                violations.append(f"{path.relative_to(PACKAGE)} -> {target}")
    assert not violations, "\n".join(sorted(violations))


def test_nothing_imports_what_moved_to_the_apps():
    found = []
    for path in [*PACKAGE.rglob("*.py"), *(PACKAGE.parent / "tests").rglob("*.py")]:
        if "node_modules" in path.parts:
            continue
        for target in _imports(path) & set(MOVED):
            found.append(f"{path.name} -> processcraft.{target} ({MOVED[target]})")
    assert not found, "\n".join(sorted(found))
    for name in MOVED:
        assert not (PACKAGE / name).exists() and not (PACKAGE / f"{name}.py").exists(), name


def test_the_sdk_never_imports_processcraft():
    sdk = PACKAGE.parent / "sdk" / "python"
    for path in sdk.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                assert name.split(".")[0] != "processcraft", f"{path} imports {name}"
