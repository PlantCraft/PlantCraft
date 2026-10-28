"""API v1 kept as published (scale review E3): its OpenAPI, what breaks it, its reference page.

``docs/api/v1/openapi.json`` is API v1 as this commit serves it; ``docs/api/v1/releases/`` holds
API v1 as each release served it. ``tests/contract/test_api_contract.py`` refuses a commit whose
API v1 differs from ``openapi.json`` (``make api-contract`` writes it again, so a change shows in
the diff) and one that breaks what a release published: a route or method removed, a parameter
or body field newly required, a response field removed, a field's type changed, a value of a
request's enum removed. Adding routes, optional parameters and response fields is not breaking.
``docs/api-v1-reference.md`` is written from the same schema, with the permission each route
needs (``plantcraft_sdk.scopes``).

    python -m processcraft.api.contract write     # openapi.json and the reference page
    python -m processcraft.api.contract release 0.5.0   # keep this commit's API v1 for a release
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

PREFIX = "/api/v1/"
ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "docs" / "api" / "v1"
CURRENT = FOLDER / "openapi.json"
RELEASES = FOLDER / "releases"
REFERENCE = ROOT / "docs" / "api-v1-reference.md"
METHODS = ("get", "put", "post", "delete", "patch", "head")


def v1_schema(openapi: dict[str, Any]) -> dict[str, Any]:
    """The API v1 part of an app's OpenAPI: its paths and the components they name."""

    paths = {
        path: {method: operation for method, operation in item.items() if method in METHODS}
        for path, item in sorted(openapi.get("paths", {}).items())
        if path.startswith(PREFIX)
    }
    schemas = openapi.get("components", {}).get("schemas", {})
    wanted: set[str] = set()
    pending = [paths]
    while pending:
        for name in _refs(pending.pop()):
            if name not in wanted and name in schemas:
                wanted.add(name)
                pending.append(schemas[name])
    return {
        "openapi": openapi.get("openapi", "3.1.0"),
        "info": {"title": "PlantCraft API v1", "version": "1"},
        "paths": paths,
        "components": {"schemas": {name: schemas[name] for name in sorted(wanted)}},
    }


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


def dumps(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# What breaks a published API v1 ----------------------------------------------------------


class _Side:
    def __init__(self, schema: dict[str, Any]):
        self.schemas = schema.get("components", {}).get("schemas", {})

    def resolve(self, node: Any, depth: int = 0) -> dict[str, Any]:
        while isinstance(node, dict) and "$ref" in node and depth < 20:
            node = self.schemas.get(str(node["$ref"]).rsplit("/", 1)[-1], {})
            depth += 1
        return node if isinstance(node, dict) else {}


def _types(node: dict[str, Any], side: _Side) -> set[str]:
    """The JSON types a schema allows (``anyOf`` unions joined); empty: anything."""

    node = side.resolve(node)
    if "type" in node:
        kind = node["type"]
        return set(kind) if isinstance(kind, list) else {kind}
    union = node.get("anyOf") or node.get("oneOf")
    if union:
        found: set[str] = set()
        for option in union:
            option_types = _types(option, side)
            if not option_types:
                return set()
            found |= option_types
        return found
    if "properties" in node:
        return {"object"}
    return set()


def _compare(
    where: str,
    old: dict[str, Any],
    new: dict[str, Any],
    sides: tuple[_Side, _Side],
    *,
    request: bool,
    seen: set[tuple[int, int]],
    problems: list[str],
) -> None:
    old, new = sides[0].resolve(old), sides[1].resolve(new)
    key = (id(old), id(new))
    if key in seen:
        return
    seen.add(key)
    old_types, new_types = _types(old, sides[0]), _types(new, sides[1])
    if old_types and new_types:
        if request and not old_types <= new_types:
            problems.append(f"{where}: accepts {sorted(new_types)}, was {sorted(old_types)}")
            return
        if not request and not new_types <= old_types:
            problems.append(f"{where}: is {sorted(new_types)}, was {sorted(old_types)}")
            return
    if request and "enum" in old and "enum" in new:
        gone = [value for value in old["enum"] if value not in new["enum"]]
        if gone:
            problems.append(f"{where}: no longer accepts {gone}")
    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    if request:
        newly = set(new.get("required", [])) - set(old.get("required", []))
        for name in sorted(newly):
            problems.append(f"{where}.{name}: is required now")
    else:
        for name in sorted(set(old_props) - set(new_props)):
            if new_props or new.get("additionalProperties") is not True:
                problems.append(f"{where}.{name}: is no longer answered")
    for name in sorted(set(old_props) & set(new_props)):
        _compare(
            f"{where}.{name}",
            old_props[name],
            new_props[name],
            sides,
            request=request,
            seen=seen,
            problems=problems,
        )
    if "items" in old and "items" in new:
        _compare(
            f"{where}[]",
            old["items"],
            new["items"],
            sides,
            request=request,
            seen=seen,
            problems=problems,
        )


def _parameters(operation: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(item["in"], item["name"]): item for item in operation.get("parameters", [])}


def _body(operation: dict[str, Any]) -> dict[str, Any] | None:
    content = (operation.get("requestBody") or {}).get("content", {})
    media = content.get("application/json") or next(iter(content.values()), None)
    return None if media is None else media.get("schema", {})


def _answer(operation: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for status, response in sorted(operation.get("responses", {}).items()):
        if status.startswith("2"):
            content = response.get("content", {})
            media = content.get("application/json")
            if media is not None:
                return status, media.get("schema", {})
    return None


def breaking(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What in ``new`` breaks a client written for ``old`` (both from ``v1_schema``)."""

    problems: list[str] = []
    sides = (_Side(old), _Side(new))
    for path, operations in sorted(old.get("paths", {}).items()):
        for method, before in sorted(operations.items()):
            after = new.get("paths", {}).get(path, {}).get(method)
            name = f"{method.upper()} {path}"
            if after is None:
                problems.append(f"{name}: removed")
                continue
            old_params, new_params = _parameters(before), _parameters(after)
            for key, param in sorted(new_params.items()):
                was = old_params.get(key)
                if param.get("required") and not (was and was.get("required")):
                    problems.append(f"{name}: {key[0]} parameter {key[1]} is required now")
            for key in sorted(set(old_params) - set(new_params)):
                problems.append(f"{name}: {key[0]} parameter {key[1]} removed")
            for key in sorted(set(old_params) & set(new_params)):
                _compare(
                    f"{name} {key[1]}",
                    old_params[key].get("schema", {}),
                    new_params[key].get("schema", {}),
                    sides,
                    request=True,
                    seen=set(),
                    problems=problems,
                )
            old_body, new_body = _body(before), _body(after)
            if new_body is not None and old_body is None and after["requestBody"].get("required"):
                problems.append(f"{name}: a body is required now")
            if old_body is not None and new_body is not None:
                _compare(
                    f"{name} body",
                    old_body,
                    new_body,
                    sides,
                    request=True,
                    seen=set(),
                    problems=problems,
                )
            old_answer, new_answer = _answer(before), _answer(after)
            if old_answer is not None and new_answer is None:
                problems.append(f"{name}: no longer answers JSON")
            elif old_answer is not None and new_answer is not None:
                _compare(
                    f"{name} answer",
                    old_answer[1],
                    new_answer[1],
                    sides,
                    request=False,
                    seen=set(),
                    problems=problems,
                )
    return problems


# The reference page -----------------------------------------------------------------------


def reference(schema: dict[str, Any]) -> str:
    """``docs/api-v1-reference.md``: every route, its permission for an app, its parameters."""

    from plantcraft_sdk.scopes import PERSON_ONLY, ROUTE_SCOPES

    lines = [
        "# API v1 reference",
        "",
        "Written by `python -m processcraft.api.contract write` from `docs/api/v1/openapi.json`;",
        "never edited by hand. The rules, the shapes and examples are in `docs/api-v1.md`.",
        "**Permission** is what an app's own token needs (its `app.toml` `[permissions]`):",
        "*any app* for every app, *people only* for a route no app's token may use.",
        "",
        "| Method | Route | Permission | Parameters | Summary |",
        "|---|---|---|---|---|",
    ]
    for path, operations in schema["paths"].items():
        for method, operation in sorted(operations.items()):
            key = (method.upper(), path)
            if key in ROUTE_SCOPES:
                permission = f"`{ROUTE_SCOPES[key]}`" if ROUTE_SCOPES[key] else "any app"
            elif key in PERSON_ONLY:
                permission = "people only"
            else:
                permission = "closed to apps"
            params = ", ".join(
                f"`{item['name']}`{'*' if item.get('required') else ''}"
                for item in operation.get("parameters", [])
                if item.get("in") in {"query", "path"}
            )
            if _body(operation) is not None:
                params = ", ".join(filter(None, [params, "JSON body"]))
            summary = (operation.get("summary") or "").replace("|", "\\|")
            lines.append(f"| {method.upper()} | `{path}` | {permission} | {params} | {summary} |")
    lines += ["", "`*` marks a required parameter.", ""]
    return "\n".join(lines)


def served() -> dict[str, Any]:
    """API v1 as this checkout serves it."""

    from processcraft.api.app import create_app

    # A scenario of its own in a folder of its own: writing the schema touches no installation.
    folder = Path(tempfile.mkdtemp(prefix="api-contract-"))
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(folder / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    (folder / "scenario.json").write_text(json.dumps(scenario))
    names = ("PLANTCRAFT_PREWARM_HISTORY", "PLANTCRAFT_WATCH", "PLANTCRAFT_MAIL_OUTBOX")
    saved = {name: os.environ.get(name) for name in ("PLANTCRAFT_SCENARIO", *names)}
    os.environ["PLANTCRAFT_SCENARIO"] = str(folder / "scenario.json")
    for name in names:
        os.environ.setdefault(name, "false")
    try:
        return v1_schema(create_app().openapi())
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(folder, ignore_errors=True)


def main(argv: list[str]) -> int:
    schema = served()
    if argv[:1] == ["write"]:
        FOLDER.mkdir(parents=True, exist_ok=True)
        CURRENT.write_text(dumps(schema))
        REFERENCE.write_text(reference(schema))
        print(f"Wrote {CURRENT.relative_to(ROOT)} and {REFERENCE.relative_to(ROOT)}")
        return 0
    if argv[:1] == ["release"] and len(argv) == 2:
        RELEASES.mkdir(parents=True, exist_ok=True)
        target = RELEASES / f"{argv[1]}.json"
        target.write_text(dumps(schema))
        print(f"Wrote {target.relative_to(ROOT)}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
