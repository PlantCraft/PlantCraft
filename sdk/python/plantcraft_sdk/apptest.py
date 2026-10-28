"""The suite's rule checks for an app's tests, written once (``docs/testing.md``).

Each function returns the problems it finds (an empty list when the app follows the rule), so an
app's ``tests/test_suite_rules.py`` stays a few lines::

    from plantcraft_sdk import apptest

    def test_offline():
        assert not apptest.offline_problems(ROOT, "twincraft")

The rules: offline by default (AGENTS.md, "Secure and offline by default"), layers that only
point down and no import of another app or of a plant protocol, the image that follows
``app.toml``, and bad input that never answers 500 (``hostile_failures``). The app's own
architecture (PlantCraft ``docs/app-standard.md``, section 5, added in SDK 0.34.0): only
``suite/`` talks to PlantCraft for the app (``suite_problems``), routers stay thin
(``router_problems``), every table of ``app.toml`` has its code (``contribution_problems``) and
the frontend copies nothing of ``@plantcraft/ui`` (``ui_copy_problems``), and the app's token
uses only what ``[permissions]`` declares (``permission_problems``, SDK 0.43.0).
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

REMOTE = re.compile(r"""(https?:)?//[a-z0-9.-]+\.[a-z]{2,}""", re.IGNORECASE)
CSS_URL = re.compile(r"""(?:@import\s+(?:url\()?|url\()\s*["']?([^"')\s;]+)""")
SCRIPT_REMOTE = re.compile(
    r"""(?:fetch|import|new\s+(?:WebSocket|EventSource|Worker))\s*\(\s*[`"'](https?:)?//"""
)
NETWORK_IMPORTS = frozenset(
    {
        "requests",
        "httpx",
        "urllib.request",
        "urllib3",
        "aiohttp",
        "anthropic",
        "openai",
        "socket",
        "asyncua",
        "psycopg",
        "psycopg_pool",
    }
)
# What no app imports: the other apps (they talk through PlantCraft only) and plant protocols
# (plant data reaches an app through PlantCraft API v1; HistCraft, the data layer, is the
# exception and lists its own).
APP_PACKAGES = frozenset(
    {
        "processcraft",
        "dashcraft",
        "linkcraft",
        "histcraft",
        "twincraft",
        "alarmcraft",
        "modelcraft",
        "doccraft",
        "plantcraft",
        "simcraft",
    }
)
PLANT_PROTOCOLS = frozenset({"asyncua", "opcua", "PIconnect", "osisoft", "pyodbc"})


def imports(path: Path) -> set[str]:
    """Every module a Python file imports (absolute imports; ``from a import b`` counts ``a`` and
    ``a.b``, since ``b`` may be a module)."""

    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            # "from app import store" imports app.store.
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def offline_problems(
    root: str | Path,
    app_id: str,
    *,
    network_modules: Iterable[str] = ("api/runtime.py",),
    client_builders: Iterable[str] = ("api/runtime.py",),
) -> list[str]:
    """Nothing external at runtime: the interface loads nothing remote, and only
    ``network_modules`` (paths under ``src/<app_id>/``) import a network library, only
    ``client_builders`` build a ``PlantCraftClient``."""

    root = Path(root)
    package = root / "src" / app_id
    frontend = root / "frontend"
    problems: list[str] = []
    index = frontend / "index.html"
    if index.is_file():
        html = index.read_text(encoding="utf-8")
        for tag in re.findall(r"<(?:script|link|img|iframe)\b[^>]*>", html, re.IGNORECASE):
            for value in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)""", tag, re.IGNORECASE):
                if REMOTE.match(value):
                    problems.append(f"frontend/index.html loads a remote resource: {tag}")
    styles = [*(frontend / "src").rglob("*.css"), *(frontend / "dist" / "static").glob("*.css")]
    for path in styles:
        for value in CSS_URL.findall(path.read_text(encoding="utf-8")):
            if REMOTE.match(value):
                problems.append(f"{_relative(path, root)} loads {value}")
    for path in (frontend / "src").rglob("*.ts*"):
        if SCRIPT_REMOTE.search(path.read_text(encoding="utf-8")):
            problems.append(f"{_relative(path, root)} reaches a remote address")
    allowed = {f"src/{app_id}/{name}" for name in network_modules}
    builders_allowed = {f"src/{app_id}/{name}" for name in client_builders}
    for path in package.rglob("*.py"):
        relative = _relative(path, root)
        used = sorted(
            name
            for name in imports(path)
            if name in NETWORK_IMPORTS or name.split(".")[0] in NETWORK_IMPORTS
        )
        if used and relative not in allowed:
            problems.append(f"{relative} opens network connections ({', '.join(used)})")
        if "PlantCraftClient(" in path.read_text(encoding="utf-8") and (
            relative not in builders_allowed
        ):
            problems.append(f"{relative} builds a PlantCraftClient (only the runtime does)")
    return problems


def layer_problems(
    root: str | Path,
    app_id: str,
    layers: Mapping[str, int],
    *,
    allowed: Iterable[str] = (),
) -> list[str]:
    """Each top-level module of ``src/<app_id>`` has a layer and imports only from lower ones
    (the top layer's modules may import each other); no app imports another app or a plant
    protocol, except the top-level packages named in ``allowed``."""

    package = Path(root) / "src" / app_id
    top = max(layers.values())
    forbidden = (APP_PACKAGES | PLANT_PROTOCOLS) - {app_id, *allowed}
    problems: list[str] = []
    for path in package.rglob("*.py"):
        if path.parent == package and path.name in {"__init__.py", "__main__.py"}:
            continue
        owner = path.relative_to(package).parts[0].removesuffix(".py")
        if owner not in layers:
            problems.append(f"{owner}: no layer (add it to the layer table)")
            continue
        for name in imports(path):
            head = name.split(".")[0]
            if head in forbidden:
                problems.append(f"{path.relative_to(package)} imports {name}")
            parts = name.split(".")
            if head != app_id or len(parts) < 2 or parts[1] == owner:
                continue
            target = layers.get(parts[1], -1)
            if target > layers[owner] or (target == layers[owner] and layers[owner] != top):
                problems.append(f"{path.relative_to(package)} -> {parts[1]} (points up)")
    return sorted(set(problems))


# Who talks to PlantCraft on the app's own behalf (docs/app-standard.md, section 5): the suite/
# folder, the runtime that builds the clients and the command line. A page reading the plant with the person's own
# token (``rt.user_client(user)``) is not this.
SUITE_ONLY_NAMES = frozenset({"service_client", "EventCatalog"})


def _suite_place(relative: str) -> bool:
    parts = relative.split("/")
    return "suite" in parts[:-1] or parts[-1] in {"runtime.py", "cli.py"}


def suite_problems(root: str | Path, app_id: str) -> list[str]:
    """Only ``src/<app_id>/suite/`` (and ``runtime.py``, ``cli.py``) talks to PlantCraft for the app: uses
    its service client or its EventCatalog. Elsewhere a module calls a function of suite/."""

    package = Path(root) / "src" / app_id
    problems: list[str] = []
    for path in package.rglob("*.py"):
        relative = path.relative_to(package).as_posix()
        if _suite_place(relative):
            continue
        used = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in SUITE_ONLY_NAMES:
                used.add(node.attr)
            elif isinstance(node, ast.Name) and node.id in SUITE_ONLY_NAMES:
                used.add(node.id)
            elif isinstance(node, ast.ImportFrom) and node.module == "plantcraft_sdk.events":
                used.update(alias.name for alias in node.names if alias.name in SUITE_ONLY_NAMES)
        if used:
            problems.append(
                f"{relative} talks to PlantCraft ({', '.join(sorted(used))}): move it to suite/"
            )
    return sorted(problems)


def router_problems(root: str | Path, app_id: str) -> list[str]:
    """``api/routers/`` stays thin: no router imports an object's ``store`` or a database
    driver; it validates, calls the object's service and answers."""

    package = Path(root) / "src" / app_id
    routers = package / "api" / "routers"
    problems: list[str] = []
    for path in sorted(routers.rglob("*.py")) if routers.is_dir() else []:
        for name in sorted(imports(path)):
            parts = name.split(".")
            if (
                parts[0] in {"sqlite3", "sqlalchemy"}
                or (parts[0] == app_id and parts[-1] == "store")
                or name == "plantcraft_sdk.server.store"
            ):
                problems.append(
                    f"api/routers/{path.relative_to(routers).as_posix()} imports {name}"
                )
    return problems


def _constants(package: Path, app_id: str) -> set[str]:
    """The strings the code names: each constant, a full kind (``"<app_id>.<name>"``) as its name,
    and ``f"{APP_ID}.<name>"`` as ``<name>``."""

    found: set[str] = set()
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
                if node.value.startswith(f"{app_id}."):
                    found.add(node.value[len(app_id) + 1 :])
            elif (
                isinstance(node, ast.JoinedStr)
                and len(node.values) == 2
                and isinstance(node.values[0], ast.FormattedValue)
                and isinstance(node.values[1], ast.Constant)
                and str(node.values[1].value).startswith(".")
            ):
                found.add(str(node.values[1].value)[1:])
    return found


def contribution_problems(
    root: str | Path, app_id: str, routes: Iterable[tuple[str, str]] = ()
) -> list[str]:
    """Every table of ``app.toml`` has its pair in the code: each declared event, calendar feed,
    to-do kind and use of a model is named (as a string) in ``src/<app_id>``, and each declared
    widget, search and reference kind has its route among ``routes`` (``api_routes(app)``)."""

    root = Path(root)
    manifest = tomllib.loads((root / "app.toml").read_text(encoding="utf-8"))
    contributes = manifest.get("contributes") or {}
    names = _constants(root / "src" / app_id, app_id)
    problems: list[str] = []
    for table, field, label in (
        (manifest.get("publishes", {}).get("events", []), "name", "event"),
        (contributes.get("calendar", []), "id", "calendar feed"),
        (contributes.get("todo", []), "id", "to-do kind"),
        (contributes.get("llm", []), "id", "use of a model"),
    ):
        for item in table:
            if item.get(field) not in names:
                problems.append(f"{label} {item.get(field)!r} is declared but no code sends it")
    paths = {path for _, path in routes}
    if routes:
        prefix = "/api/"
        for widget in contributes.get("widgets", []):
            if not any(path.startswith(f"{prefix}widgets/") for path in paths):
                problems.append(f"widget {widget.get('id')!r} is declared but no route serves it")
        if f"{prefix}widgets" in paths and not contributes.get("widgets"):
            problems.append("widgets are served but none is declared in [[contributes.widgets]]")
        for widget in contributes.get("widgets", []):
            if widget.get("pick") and f"{prefix}widgets/{{widget_id}}/options" not in paths:
                problems.append(
                    f"widget {widget.get('id')!r} has a pick but no route serves its options"
                )
        if contributes.get("search") and f"{prefix}search" not in paths:
            problems.append("search is declared but no route answers /api/search")
        for ref in contributes.get("refs", []):
            if not any(path.startswith(f"{prefix}refs/") for path in paths):
                problems.append(
                    f"reference kind {ref.get('kind')!r} is declared but no route names it"
                )
        if contributes.get("objects") and f"{prefix}objects/{{kind}}" not in paths:
            problems.append("objects are declared but no route serves /api/objects/<kind>")
        notebooks = contributes.get("notebooks") or {}
        if notebooks.get("examples") and f"{prefix}notebooks/examples" not in paths:
            problems.append("examples are declared but no route serves /api/notebooks/examples")
        if notebooks.get("runtime") and f"{prefix}notebooks/runtime" not in paths:
            problems.append("a runtime is declared but no route serves /api/notebooks/runtime")
    return problems


def objects_problems(client: Any, prefix: str, root: str | Path = ".") -> list[str]:
    """Every kind of ``[[contributes.objects]]`` answers its list in ``plantcraft-objects/1``
    (items with an ``id`` and a ``name``), its first item by id, and a 404 for an unknown id; the
    examples are written right and the runtime holds its entry (PlantCraft docs/en/notebooks.md,
    "The apps' objects"). ``client`` is a signed-in test client, ``prefix`` the app's (``/link``)."""

    from plantcraft_sdk.server.objects import FORMAT

    manifest = tomllib.loads((Path(root) / "app.toml").read_text(encoding="utf-8"))
    contributes = manifest.get("contributes") or {}
    base = prefix.rstrip("/")
    problems: list[str] = []
    for spec in contributes.get("objects", []):
        kind = spec.get("kind")
        answer = client.get(f"{base}/api/objects/{kind}")
        if answer.status_code != 200:
            problems.append(f"objects {kind!r}: the list answered {answer.status_code}")
            continue
        body = answer.json()
        if body.get("format") != FORMAT or not isinstance(body.get("items"), list):
            problems.append(f"objects {kind!r}: the list is not {FORMAT}")
            continue
        bad = [item for item in body["items"] if not (item.get("id") and item.get("name"))]
        if bad:
            problems.append(f"objects {kind!r}: {len(bad)} items without an id or a name")
        if body["items"]:
            first = body["items"][0]["id"]
            one = client.get(f"{base}/api/objects/{kind}/{first}")
            if one.status_code != 200 or one.json().get("id") != first:
                problems.append(f"objects {kind!r}: {first!r} of the list does not open")
        missing = client.get(f"{base}/api/objects/{kind}/no-such-object-here")
        if missing.status_code != 404:
            problems.append(f"objects {kind!r}: an unknown id answered {missing.status_code}")
        if spec.get("run") == "app":
            # Off by default or not found: refused, never started and never a server error.
            started = client.post(
                f"{base}/api/objects/{kind}/run", json={"id": "no-such-object-here"}
            )
            if started.status_code not in (403, 404, 409, 422):
                problems.append(
                    f"objects {kind!r}: running an unknown id answered {started.status_code}"
                )
    notebooks = contributes.get("notebooks") or {}
    if notebooks.get("examples"):
        listing = client.get(f"{base}/api/notebooks/examples")
        items = listing.json().get("items", []) if listing.status_code == 200 else None
        if not items:
            problems.append("examples are declared but none is served")
        for item in items or []:
            found = client.get(f"{base}/api/notebooks/examples/{item['id']}")
            if found.status_code != 200 or found.json().get("nbformat") != 4:
                problems.append(f"example {item['id']!r} is not a notebook")
    if notebooks.get("runtime"):
        import io
        import zipfile

        found = client.get(f"{base}/api/notebooks/runtime")
        if found.status_code != 200:
            problems.append(f"the runtime answered {found.status_code}")
        else:
            names = zipfile.ZipFile(io.BytesIO(found.content)).namelist()
            entry = str(notebooks.get("entry") or "").replace(".", "/")
            if f"{entry}.py" not in names and f"{entry}/__init__.py" not in names:
                problems.append(f"the runtime does not hold its entry {notebooks.get('entry')!r}")
    return problems


def permission_problems(root: str | Path, app_id: str) -> list[str]:
    """What the app's own token used in this test run's fakes (``FakePlantCraft``) that its
    ``app.toml`` ``[permissions]`` does not declare (scale review E4): PlantCraft answers those
    routes 403 to the app. Call it once the app's tests ran (a ``pytest_sessionfinish`` hook)."""

    from plantcraft_sdk.scopes import declared
    from plantcraft_sdk.testing import PERMISSIONS_USED

    manifest = tomllib.loads((Path(root) / "app.toml").read_text(encoding="utf-8"))
    table = manifest.get("permissions") or {}
    have = declared(table.get("read", []), table.get("write", []))
    return [
        f"{app_id} uses {scope} but app.toml [permissions] does not declare it"
        for scope in sorted(PERMISSIONS_USED.get(app_id, set()) - have)
    ]


WIDGET_KINDS = ("number", "list", "split", "series", "facts", "bars", "columns", "tiles")


# A list row's value that is only a time from now ("5 h ago"): nobody can tell what happened
# then, so the time goes in the line below the name with its word ("Updated 5 h ago").
BARE_TIME = re.compile(r"^(just now|\d+ (min|h|d) ago|in \d+ (min|h|d))$")


def widget_problems(client: Any, prefix: str) -> list[str]:
    """Every widget the app serves answers in the shape it declares, with links on its own
    host; a widget with ``pick`` lists its options and answers for the first of them, and
    unknown widgets are a 404 (PlantCraft ``docs/widgets.md``). ``client`` is a signed-in
    test client, ``prefix`` the app's (``/link``)."""

    base = f"{prefix.rstrip('/')}/api/widgets"
    problems: list[str] = []
    listed = client.get(base)
    if listed.status_code != 200:
        return [f"{base} answered {listed.status_code}"]
    body = listed.json()
    if body.get("version") != 1:
        problems.append(f"{base}: version {body.get('version')!r}, not 1")

    def links(widget_id: str, data: dict[str, Any]) -> None:
        found = [data.get("href")]
        for key in ("items", "parts", "bars", "groups"):
            found += [row.get("href") for row in data.get(key) or [] if isinstance(row, dict)]
        for entry in data.get("groups") or []:
            if isinstance(entry, dict):
                found += [
                    row.get("href") for row in entry.get("tiles") or [] if isinstance(row, dict)
                ]
        for href in found:
            if href is not None and not (
                str(href).startswith("/") and not str(href).startswith("//")
            ):
                problems.append(f"widget {widget_id!r}: link {href!r} is not on this host")

    for widget in body.get("widgets", []):
        widget_id = widget.get("id")
        kind = widget.get("kind", "list")
        if kind not in WIDGET_KINDS:
            problems.append(f"widget {widget_id!r}: unknown kind {kind!r}")
        urls = [f"{base}/{widget_id}"]
        if widget.get("pick"):
            answer = client.get(f"{base}/{widget_id}/options")
            options = answer.json().get("options") if answer.status_code == 200 else None
            if not isinstance(options, list):
                problems.append(f"widget {widget_id!r}: its options answered {answer.status_code}")
            elif options:
                urls.append(f"{base}/{widget_id}?item={quote(str(options[0]['value']), safe='')}")
            urls.append(f"{base}/{widget_id}?item=no-such-thing")
        for url in urls:
            answer = client.get(url)
            if answer.status_code != 200:
                problems.append(f"{url} answered {answer.status_code}")
                continue
            data = answer.json()
            if data.get("kind") != kind:
                problems.append(f"{url}: kind {data.get('kind')!r}, declared {kind!r}")
            links(str(widget_id), data)
            for row in data.get("items") or [] if data.get("kind") == "list" else []:
                if isinstance(row, dict) and BARE_TIME.match(str(row.get("value") or "")):
                    problems.append(
                        f"widget {widget_id!r}: {row.get('value')!r} alone does not say what"
                        " happened then; put the time in the line below the name"
                        ' ("Updated 5 h ago")'
                    )
    if client.get(f"{base}/no-such-widget").status_code != 404:
        problems.append(f"{base}/no-such-widget is not a 404")
    return problems


def ui_copy_problems(root: str | Path, ui_src: str | Path | None = None) -> list[str]:
    """The frontend copies nothing of ``@plantcraft/ui``: no file with the same bytes as one of
    the package's (``ui_src``, its ``src`` folder, when given), and no ``Plot.tsx``, ``HelpPage.tsx``
    or ``brandTheme`` of its own. Re-exporting or wrapping the package's is fine (the file imports
    ``@plantcraft/ui``), and so is a type declaration (``.d.ts``) the package's sources need."""

    source = Path(root) / "frontend" / "src"
    problems: list[str] = []
    if not source.is_dir():
        return problems
    theirs: dict[bytes, str] = {}
    if ui_src is not None and Path(ui_src).is_dir():
        for path in Path(ui_src).rglob("*.ts*"):
            theirs[path.read_bytes()] = path.name
    for path in sorted(source.rglob("*.ts*")):
        relative = path.relative_to(source).as_posix()
        data = path.read_bytes()
        if path.name.endswith(".d.ts"):
            continue
        if data in theirs:
            problems.append(f"frontend/src/{relative} is a copy of @plantcraft/ui's {theirs[data]}")
        elif path.name in {"Plot.tsx", "HelpPage.tsx"} and b'"@plantcraft/ui' not in data:
            problems.append(
                f"frontend/src/{relative}: the suite's {path.stem} comes from @plantcraft/ui"
            )
        elif path.stem == "brandTheme" and b"export function" in data:
            problems.append(
                f"frontend/src/{relative} defines the suite's colours: re-export @plantcraft/ui's"
            )
    return problems


def image_problems(root: str | Path) -> list[str]:
    """The Dockerfile follows ``app.toml``: user, port, health check, labels and the SBOM."""

    root = Path(root)
    app = tomllib.loads((root / "app.toml").read_text(encoding="utf-8"))
    docker = (root / "Dockerfile").read_text(encoding="utf-8")
    # A Dockerfile may name the values once as ARGs (ARG APP_PORT=8140, then ${APP_PORT}).
    args = dict(re.findall(r"^ARG (\w+)=\"?([^\"\n]*)\"?$", docker, re.MULTILINE))
    docker = re.sub(r"\$\{(\w+)\}", lambda match: args.get(match.group(1), match.group(0)), docker)
    runtime, meta = app["runtime"], app["app"]
    expected = {
        f"USER {runtime['uid']}:{runtime['uid']}": "the app's uid",
        f"EXPOSE {runtime['port']}": "the app's port",
        f"127.0.0.1:{runtime['port']}{runtime['health']}": "the health check",
        f'org.processcraft.app.id="{meta["id"]}"': "the id label",
        f'org.processcraft.app.prefix="{runtime["prefix"]}"': "the prefix label",
        f'org.processcraft.app.port="{runtime["port"]}"': "the port label",
        "plantcraft_sdk.sbom --here": "the SBOM at build (python -m plantcraft_sdk.sbom)",
        "> /app/sbom.json": "the SBOM in /app/sbom.json",
    }
    problems = [
        f"Dockerfile: no {what} ({text})" for text, what in expected.items() if text not in docker
    ]
    if meta.get("summary") and meta["summary"] not in docker:
        problems.append("Dockerfile: the description label is not app.toml's summary")
    return problems


def api_routes(app: Any) -> list[tuple[str, str]]:
    """Every documented operation of an app's API, as ``(METHOD, /api/path)``; ``app`` is what
    ``create_app`` returns (``app.state.api`` is the API under the prefix)."""

    api = getattr(app.state, "api", app)
    routes = []
    for path, operations in api.openapi()["paths"].items():
        if path.startswith("/api/"):
            routes.extend((method.upper(), path) for method in sorted(operations))
    return routes


def open_routes(
    client: Any, *, prefix: str = "", open_paths: Iterable[str] = ()
) -> tuple[list[str], int]:
    """Every API route asked without a token: the ones that answered anyway, and how many routes
    were reached (a route the walk could not reach counts as open, so a wrong ``prefix`` fails).

    ``client`` is a ``TestClient`` with no ``Authorization`` header; ``prefix`` is what to put
    before ``/api/...`` (``"/link"`` when the client's base URL does not carry it). ``open_paths``
    are the routes meant to answer without a token (a public dashboard link), as documented
    paths: ``"/api/public/{token}"``.
    """

    allowed = set(open_paths)
    leaks: list[str] = []
    reached = 0
    for method, path in api_routes(client.app):
        if path in allowed:
            continue
        target = prefix.rstrip("/") + PARAM.sub("x", path)
        body = {} if method in {"POST", "PUT", "PATCH"} else None
        response = client.request(method, target.lstrip("/"), json=body)
        if response.status_code in (401, 403):
            reached += 1
            continue
        leaks.append(f"{method} {path} -> {response.status_code} {response.text[:80]}")
    return leaks, reached


JUNK_SEGMENTS = (
    "x",
    "%2e%2e",
    "..%2F..%2Fetc%2Fpasswd",
    "a" * 400,
    "' OR 1=1 --",
    "ç☃",
    "-1",
    "NaN",
)
JUNK_BODIES: tuple[Any, ...] = (
    None,
    {},
    [],
    "not json",
    {"name": None},
    {"name": "x" * 10_000},
    {"start": "yesterday", "end": "2026-13-45", "window": "9999999d"},
    {"window": "-1h"},
    {"enabled": "maybe"},
)
JUNK_QUERIES: tuple[dict[str, str], ...] = (
    {"window": "-1", "limit": "abc"},
    {"asset": "nowhere", "q": "%", "kind": "\x00"},
    {"asset": "x" * 400, "limit": "99999", "name": "x" * 500},
)
PARAM = re.compile(r"\{[^}]+\}")


def hostile_failures(
    client: Any,
    *,
    real: Mapping[str, str] | None = None,
    bodies: Iterable[Any] = (),
    queries: Iterable[dict[str, str]] = (),
    keep: Iterable[str] = (),
) -> tuple[list[str], int]:
    """Every API route fed with junk paths, bodies and queries (each body and each query at least
    once on each path); returns the answers that were a server error (500 and up, 503 excepted)
    and how many requests got past the 404.

    ``client`` is a ``TestClient`` signed in (as an admin) under the app's prefix. ``real``
    names a real object for each path parameter (``{"twin_id": "..."}``) so validation past the
    lookup is reached too; ``keep`` are those real ids never sent a DELETE. ``bodies`` and
    ``queries`` are the app's own junk, sent with ``JUNK_BODIES`` and ``JUNK_QUERIES``.
    """

    real = dict(real or {})
    keep = set(keep)
    junk_bodies = [*JUNK_BODIES, *bodies]
    junk_queries = [*JUNK_QUERIES, *queries]
    failures: list[str] = []
    answered = 0
    for method, path in api_routes(client.app):
        targets = [path]
        if PARAM.search(path):
            targets = [PARAM.sub(segment, path) for segment in JUNK_SEGMENTS]
            targets.append(PARAM.sub(lambda match: real.get(match.group(0)[1:-1], "x"), path))
        for target in targets:
            if method == "DELETE" and any(target.endswith(f"/{kept}") for kept in keep):
                continue
            sent = junk_bodies if method in {"POST", "PUT", "PATCH"} else [None]
            # Every body and every query once, paired round-robin: a full product would square
            # the run time and finds nothing more (handlers check bodies and queries apart).
            for index in range(max(len(sent), len(junk_queries))):
                body, query = sent[index % len(sent)], junk_queries[index % len(junk_queries)]
                kwargs: dict[str, Any] = {}
                if isinstance(body, str):
                    kwargs = {"content": body, "headers": {"Content-Type": "application/json"}}
                elif body is not None:
                    kwargs = {"json": body}
                response = client.request(method, target.lstrip("/"), params=query, **kwargs)
                answered += response.status_code != 404
                if response.status_code >= 500 and response.status_code != 503:
                    failures.append(
                        f"{method} {target[:80]} body={str(body)[:40]!r} -> "
                        f"{response.status_code} {response.text[:120]}"
                    )
    return failures, answered


def _without_columns(schema: str, added: Mapping[str, Iterable[str]]) -> str:
    """``schema`` as a release before ``added`` wrote it: those columns out of their
    ``CREATE TABLE`` and the indexes that name them left out."""

    statements = []
    # Comments out first: a statement then starts with its keyword, a column line with its name.
    plain = "\n".join(line.split("--")[0].rstrip() for line in schema.splitlines())
    for statement in (part.strip() for part in plain.split(";")):
        if not statement:
            continue
        table = re.match(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)", statement, re.I)
        if table and table.group(1) in added:
            gone = set(added[table.group(1)])
            head, _, body = statement.partition("(")
            body = body.rsplit(")", 1)[0]
            lines = [line for line in body.split("\n") if line.strip()]
            kept = [line.rstrip().rstrip(",") for line in lines if line.split()[0] not in gone]
            statement = f"{head}(\n" + ",\n".join(kept) + "\n)"
        index = re.match(
            r"CREATE (?:UNIQUE )?INDEX(?: IF NOT EXISTS)?\s+\w+\s+ON\s+(\w+)", statement, re.I
        )
        if index and index.group(1) in added:
            columns = statement[statement.index("(") :]
            if any(re.search(rf"\b{column}\b", columns) for column in added[index.group(1)]):
                continue
        statements.append(statement)
    return ";\n".join(statements) + ";\n"


def upgrade_problems(store_class: type, open_store: Any, folder: str | Path) -> list[str]:
    """Open a store on a database from before its ``add_columns`` steps (scale review E10).

    The tables are created as an older release wrote them (``SCHEMA`` without the columns its
    ``MIGRATIONS`` add, and without the indexes that name them), then ``open_store(database)``
    opens it twice: every column must be there, every step recorded once, and nothing may fail
    (an index in ``SCHEMA`` on a column a step adds would, on a real upgrade)::

        def test_an_older_database_opens(tmp_path):
            assert not apptest.upgrade_problems(RunStore, RunStore, tmp_path)
    """

    import sqlite3

    from plantcraft_sdk.server.store import Database

    added: dict[str, list[str]] = {}
    for step in getattr(store_class, "MIGRATIONS", ()):
        table, columns = getattr(step.run, "table", None), getattr(step.run, "columns", None)
        if table and columns:
            added.setdefault(table, []).extend(columns)
    if not added:
        return [f"{store_class.__qualname__} has no add_columns step to try"]
    Path(folder).mkdir(parents=True, exist_ok=True)
    path = Path(folder) / f"upgrade-{store_class.__name__}.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(_without_columns(store_class.SCHEMA, added))
    problems = []
    for attempt in (1, 2):
        try:
            open_store(Database(path))
        except Exception as exc:  # noqa: BLE001 - the problem is the answer
            return [
                f"{store_class.__qualname__}: opening an older database failed ({attempt}): {exc}"
            ]
    with sqlite3.connect(path) as connection:
        for table, columns in added.items():
            have = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            problems += [
                f"{table}.{column} was not added" for column in columns if column not in have
            ]
        done = [row[0] for row in connection.execute("SELECT name FROM sdk_migrations")]
    for step in store_class.MIGRATIONS:
        key = f"{store_class.__qualname__}:{step.name}"
        if done.count(key) != 1:
            problems.append(f"{key} is recorded {done.count(key)} times")
    return problems


def run_examples(
    examples: Any,
    client: Any,
    prefix: str,
    fake: Any,
    *,
    root: str | Path = ".",
    username: str = "engineer",
    library: str | Path | None = None,
    workdir: str | Path | None = None,
) -> list[str]:
    """Run every cell of the app's notebook examples as a person's notebook runs them, against
    the app (``client``, signed in) and the fake PlantCraft; what failed, by example and cell.

    The cells run in ``workdir`` (a folder of their own by default), where an example saves its
    files. ``plantcraft_notebook`` (PlantCraft's ``notebooks/python``, found from ``root`` in the
    monorepo or given as ``library``) is the notebook's own library: its reads of API v1 go to
    ``fake``, its reads of the app's objects to ``client`` as PlantCraft would forward them
    (``/api/v1/apps/<app>/objects/...`` to ``<prefix>/api/objects/...``)."""

    import importlib
    import sys
    import traceback

    from plantcraft_sdk.testing import BASE_URL

    folder = Path(library) if library else Path(root).resolve().parents[1] / "notebooks" / "python"
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    pc = importlib.import_module("plantcraft_notebook")
    import pandas as pd

    backend = pd.get_option("plotting.backend")
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        # An app without matplotlib in its tests: the plots are asked, not drawn.
        plt = None
        sys.modules.setdefault("plantcraft_sdk._no_plots", _NoPlots)  # type: ignore[arg-type]
        pd.set_option("plotting.backend", "plantcraft_sdk._no_plots")
    manifest = tomllib.loads((Path(root) / "app.toml").read_text(encoding="utf-8"))
    app_id = manifest["app"]["id"]
    contributes = manifest.get("contributes") or {}
    offer = {
        "app": app_id,
        "name": manifest["app"].get("name") or app_id,
        "prefix": prefix.rstrip("/") + "/",
        "version": manifest["app"].get("version") or "",
        "kinds": [
            {
                "kind": spec["kind"],
                "title": spec.get("title") or spec["kind"],
                "description": spec.get("description") or "",
                "run": spec.get("run") or "none",
            }
            for spec in contributes.get("objects", [])
        ],
        "examples": bool((contributes.get("notebooks") or {}).get("examples")),
        "runtime": bool((contributes.get("notebooks") or {}).get("entry")),
    }
    forwarded = re.compile(rf"^/api/v1/apps/{re.escape(app_id)}/(objects|notebooks)/(.*)$")
    plant = fake.http_client()
    token = fake.token(username)
    base = prefix.rstrip("/")

    def answer(method: str, path: str, body: bytes | None) -> Any:
        if path.split("?")[0] == "/api/v1/objects":
            return SimpleAnswer(200, json.dumps({"apps": [offer]}).encode())
        found = forwarded.match(path)
        if found:
            reply = client.request(method, f"{base}/api/{found[1]}/{found[2]}", content=body)
            return SimpleAnswer(reply.status_code, reply.content)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        reply = plant.request(method, BASE_URL + path, content=body, headers=headers)
        return SimpleAnswer(reply.status_code, reply.content)

    def computer(self: Any, method: str, path: str, body: bytes | None) -> tuple[int, str, str]:
        reply = answer(method, path, body)
        return reply.status, reply.body.decode("utf-8", "replace"), ""

    def download(self: Any, path: str) -> bytes:
        reply = answer("GET", path, None)
        if reply.status >= 400:
            raise pc.PlantCraftError(reply.status, reply.body.decode("utf-8", "replace"))
        return reply.body

    import os
    import tempfile

    saved = (pc.Client._computer, pc.Client.download, getattr(pc, "_client", None))
    saved_path, saved_dir = list(sys.path), os.environ.get("PLANTCRAFT_RUNTIME_DIR")
    runtimes = sys.modules["plantcraft_notebook.apps"]._RUNTIMES
    pc.Client._computer, pc.Client.download = computer, download
    scratch = tempfile.TemporaryDirectory(prefix="plantcraft-runtimes-")
    os.environ["PLANTCRAFT_RUNTIME_DIR"] = str(Path(scratch.name) / "runtimes")
    here = os.getcwd()
    os.chdir(workdir or scratch.name)
    problems: list[str] = []
    try:
        pc.connect(BASE_URL, token=token)
        for example in examples:
            cells = example.notebook()["cells"]
            # The first cells say what the example is and install the library: here it is imported.
            space: dict[str, Any] = {"pc": pc}
            for number, item in enumerate(cells[2:], start=3):
                if item["cell_type"] != "code":
                    continue
                try:
                    exec(compile(item["source"], f"<{example.id} cell {number}>", "exec"), space)  # noqa: S102
                except Exception:  # every failure is reported with its cell
                    problems.append(f"{example.id}, cell {number}: {traceback.format_exc(limit=3)}")
                    break
            if plt is not None:
                plt.close("all")
    finally:
        os.chdir(here)
        pc.Client._computer, pc.Client.download, pc._client = saved
        sys.path[:] = saved_path
        runtimes.clear()
        pd.set_option("plotting.backend", backend)
        if saved_dir is None:
            os.environ.pop("PLANTCRAFT_RUNTIME_DIR", None)
        else:
            os.environ["PLANTCRAFT_RUNTIME_DIR"] = saved_dir
        scratch.cleanup()
    return problems


@dataclass(frozen=True)
class SimpleAnswer:
    status: int
    body: bytes


class _Drawn:
    """What a plot answers when nothing is drawn: every call gives it back (``ax.legend()``)."""

    def __getattr__(self, _name: str) -> Any:
        return lambda *args, **kwargs: self

    def __getitem__(self, _key: Any) -> _Drawn:
        return self


class _NoPlots:
    """A pandas plotting backend that draws nothing (``pd.options.plotting.backend``)."""

    @staticmethod
    def plot(_data: Any, *args: Any, **kwargs: Any) -> _Drawn:
        return _Drawn()
