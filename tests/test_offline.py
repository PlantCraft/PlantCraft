"""Offline by default: nothing external is loaded at runtime.

Fonts, scripts and styles are bundled; only the data sources an administrator
configures (PI Web API, OPC UA) may open outbound connections. The browser side
is also checked live by the e2e fixtures, which fail on any request outside the
server.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REMOTE = re.compile(r"""(https?:)?//[a-z0-9.-]+\.[a-z]{2,}""", re.IGNORECASE)
# Modules allowed to open network connections, each to an address an administrator configures.
NETWORK_MODULES = {
    "plantcraft/industrial_data/pi_web_api.py",  # the configured PI Web API
    "plantcraft/industrial_data/pi_check.py",  # diagnosis of that same PI Web API
    # The online app catalog (only when PLANTCRAFT_APP_CATALOG_URL is set; off by default) and
    # the health check of an external app's address an administrator registers.
    "plantcraft/apps/remote.py",
    # HistCraft, the data layer, only when HISTCRAFT_URL is set (off by default).
    "plantcraft/platform/datalayer/histcraft.py",
    # A specialist's language model, only when an admin turns it on with a key (off by default;
    # PLANTCRAFT_LLM=off forbids it in the installation, docs/collaboration.md).
    "plantcraft/specialists/model.py",
    # llm-egress, the proxy those calls take to a model in the cloud: tunnels only to the hosts
    # of the providers an admin added (none: it opens nothing), plus Health's look at it.
    "plantcraft/egress/__init__.py",
    # `processcraft demo seed`, run by an administrator (install.sh --public-demo): the suite's
    # own services inside the installation's network, never an outside address.
    "plantcraft/demo_seed.py",
    # The suite's health: GET /api/ops/metrics of the suite's own servers, at their Compose
    # services inside the installation's network (PLANTCRAFT_OPS_URLS may name others).
    "plantcraft/watch/recorder.py",
    # Operations › Logs: GET /api/ops/logs of those same servers, with the same short ops token.
    "plantcraft/watch/logs.py",
    # Corporate sign-in, only when an admin turns it on (off by default; the installation forbids
    # it with PLANTCRAFT_CORPORATE_LOGIN=off): the company's directory and sign-in provider,
    # inside the plant's network (docs/corporate-login.md).
    "plantcraft/directory/ldap.py",
    "plantcraft/directory/oidc.py",
    # The MCP server answers each tool with this process's own API v1, through httpx's ASGI
    # transport: an in-process call, never a socket (docs/assistant-access.md).
    "plantcraft/assistant_access/mcp.py",
    # A notebook's reads of an app's objects, forwarded to the app inside the suite's network
    # (GET only, under its api/objects/ and api/notebooks/; docs/api-v1.md).
    "plantcraft/api/app_proxy.py",
    # Desk's calendar links, only when an admin turns them on and names the servers allowed (off
    # by default; importing an .ics file needs no network, docs/desk.md).
    "plantcraft/desk/__init__.py",
}
NETWORK_IMPORTS = {
    "requests",
    "httpx",
    "urllib.request",
    "urllib3",
    "aiohttp",
    "anthropic",
    "openai",
    "socket",
    "ldap3",
}


def test_index_html_loads_nothing_remote():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    for tag in re.findall(r"<(?:script|link|img|iframe)\b[^>]*>", html, re.IGNORECASE):
        for attribute in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)""", tag, re.IGNORECASE):
            assert not REMOTE.match(attribute), f"remote resource in index.html: {tag}"


def test_stylesheets_load_nothing_remote():
    for path in (FRONTEND / "src").rglob("*.css"):
        text = path.read_text(encoding="utf-8")
        for match in re.findall(r"""(?:@import\s+(?:url\()?|url\()\s*["']?([^"')\s;]+)""", text):
            assert not REMOTE.match(match), f"{path.relative_to(ROOT)} loads {match}"


def test_scripts_fetch_only_the_own_server():
    pattern = re.compile(
        r"""(?:fetch|import|new\s+(?:WebSocket|EventSource|Worker))\s*\(\s*[`"'](https?:)?//"""
    )
    for path in (FRONTEND / "src").rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path.relative_to(ROOT)} reaches a remote address"


def test_built_assets_load_no_remote_styles_or_fonts():
    dist = FRONTEND / "dist" / "assets"
    if not dist.is_dir():
        return
    for path in dist.glob("*.css"):
        text = path.read_text(encoding="utf-8")
        for match in re.findall(r"""(?:@import\s+(?:url\()?|url\()\s*["']?([^"')\s;]+)""", text):
            assert not REMOTE.match(match), f"built {path.name} loads {match}"


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_only_known_modules_open_network_connections():
    offenders = []
    for path in (ROOT / "plantcraft").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        used = {
            name
            for name in _imports(path)
            if name in NETWORK_IMPORTS or name.split(".")[0] in NETWORK_IMPORTS
        }
        if used and relative not in NETWORK_MODULES:
            offenders.append(f"{relative}: {sorted(used)}")
    assert not offenders, "\n".join(offenders)
