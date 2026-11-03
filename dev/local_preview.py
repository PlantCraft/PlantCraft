#!/usr/bin/env python3
"""Local preview: the site and the whole suite with the demo story, on this machine, without
publishing anything (docs/development.md, "Local preview").

    make preview          the suite in Docker (the images of this checkout) + the site
    make preview-light    the same without Docker: every server from source (cloud sessions)
    make preview-reset    fresh data and the demo story again, in the same mode
    make preview-down     stop it (data kept)
    make preview-shots    screenshots of the main pages into <folder>/shots/
    make preview-status   what runs and where

Everything lives in its own folder (PREVIEW_DIR, default ~/plantcraft-preview), under its own
Compose project (plantcraft-preview) and ports (PREVIEW_PORT, default 8260 the suite and 8261 the
site), so it never touches another installation on the machine (~/PlantCraft, ~/plantcraft-ci).
MODE=public-demo opens the demo to visitors as on the public demo (the "Enter the demo" button).

Docker mode installs with deploy/install.sh --dev from a copy of deploy/, after building the
images of this checkout and tagging them <version>-preview; the plain <version> tags are put
back where they were, so another suite on the machine keeps its images.

Light mode runs PlantCraft, the six apps, the Simulator and the site as processes from this
checkout, in a virtual environment of its own (<folder>/venv), behind a small proxy that routes
the apps' prefixes as the suite's Caddy proxy does: one address, one sign-in.

The script runs on the Python macOS ships (3.9) and newer; the servers run on Python 3.12 or 3.13.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = Path.home() / "plantcraft-preview"
PROJECT = "plantcraft-preview"
DEFAULT_PORT = 8260
# Folders another suite on the Mac mini lives in: the preview never installs there.
FORBIDDEN = [Path.home() / name for name in ("PlantCraft", "ProcessCraft", "plantcraft-ci")]

# The suite's apps as deploy/compose.yaml runs them: id, folder, prefix. In light mode each gets
# the suite port + 11, + 12...; PlantCraft itself + 10 and the Simulator's OPC UA port 4841.
APPS = [
    ("linkcraft", "apps/link", "/link/"),
    ("histcraft", "apps/historian", "/hist/"),
    ("dashcraft", "apps/view", "/dash/"),
    ("alarmcraft", "apps/alarms", "/alarm/"),
    ("modelcraft", "apps/models", "/model/"),
    ("doccraft", "apps/documents", "/doc/"),
]
# The prefixes whose pages PlantCraft frames for a signed-in person (deploy/proxy/Caddyfile, @frame).
FRAMED = ("/link/", "/dash/", "/hist/", "/alarm/", "/model/")
OPCUA_PORT = 4841
# Pages preview-shots takes (path, file name); the apps' first pages follow.
SUITE_PAGES = [
    ("/", "suite-home"),
    ("/assets", "suite-assets"),
    ("/actions", "suite-actions"),
    ("/calendar", "suite-calendar"),
    ("/health", "suite-health"),
    ("/users", "suite-users"),
    ("/admin", "suite-admin"),
]


def log(message: str) -> None:
    print(f"[preview] {message}", flush=True)


def die(message: str) -> None:
    print(f"[preview] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


class Layout:
    """Where everything of one preview lives, and its ports."""

    def __init__(self, folder: Path, port: int):
        self.dir = folder
        self.port = port
        self.site_port = port + 1
        self.platform_port = port + 10
        self.venv = folder / "venv"
        self.python = self.venv / "bin" / "python"
        self.light = folder / "light"
        self.data = self.light / "data"
        self.logs = folder / "logs"
        self.suite = folder / "suite"  # Docker mode: the install folder
        self.bundle = folder / "bundle"  # Docker mode: the copy of deploy/ install.sh runs from
        self.site = folder / "site"
        self.shots = folder / "shots"
        self.state = folder / "state.json"

    def app_port(self, index: int) -> int:
        return self.platform_port + 1 + index

    def read_state(self) -> dict:
        try:
            return json.loads(self.state.read_text())
        except (OSError, ValueError):
            return {}

    def write_state(self, **values) -> None:
        state = self.read_state()
        state.update(values)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state.write_text(json.dumps(state, indent=2))


# Small helpers --------------------------------------------------------------------------------


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def http_ok(url: str) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as answer:
            return answer.status < 500
    except urllib.error.HTTPError as error:
        return error.code < 500
    except (OSError, ValueError):
        return False


def wait_for(what: str, check, seconds: float, process: subprocess.Popen | None = None) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        if process is not None and process.poll() is not None:
            die(f"{what} stopped (exit {process.returncode}): see its log")
        time.sleep(1)
    die(f"{what} not ready after {int(seconds)} s")


def run(command: list, **options) -> None:
    printable = " ".join(str(part) for part in command)
    log(f"$ {printable}")
    subprocess.run([str(part) for part in command], check=True, **options)


def secret_file(path: Path, value: str | None = None) -> str:
    """A secret kept in ``path`` (made once, 0600)."""

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value or secrets.token_urlsafe(18))
        path.chmod(0o600)
    return path.read_text().strip()


def time_zone() -> str:
    if os.environ.get("TZ", "").count("/") == 1:
        return os.environ["TZ"]
    try:
        target = os.readlink("/etc/localtime")
        return target.split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


def version_of(folder: Path) -> str:
    text = (folder / "pyproject.toml").read_text()
    for line in text.splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    die(f"no version in {folder}/pyproject.toml")
    return ""


def check_folder(layout: Layout) -> None:
    folder = layout.dir.resolve()
    for other in FORBIDDEN:
        if folder == other.resolve() or other.resolve() in folder.parents:
            die(f"{folder} is another installation's folder: choose another PREVIEW_DIR")
    env = layout.suite / ".env"
    if env.exists() and f"COMPOSE_PROJECT_NAME={PROJECT}" not in env.read_text():
        die(f"{env} is not a preview's (COMPOSE_PROJECT_NAME): choose another PREVIEW_DIR")


# The virtual environment and the interfaces ------------------------------------------------------


def server_python() -> str:
    for name in ("python3.13", "python3.12"):
        found = shutil.which(name)
        if found:
            return found
    if sys.version_info[:2] in ((3, 12), (3, 13)):
        return sys.executable
    die("Python 3.12 or 3.13 is needed for the servers (asyncua fails on newer ones)")
    return ""


def ensure_venv(layout: Layout, suite: bool) -> None:
    """``<folder>/venv`` with the site (both modes) and, for light mode, the suite from source."""

    marker = layout.venv / ("preview-suite" if suite else "preview-site")
    if marker.exists():
        return
    if not layout.python.exists():
        log(f"virtual environment in {layout.venv}")
        run([server_python(), "-m", "venv", layout.venv])
        run([layout.python, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    packages = ["-e", ROOT / "site"]
    if suite:
        packages += ["-e", ROOT / "sdk" / "python", "-e", f"{ROOT}[server,opcua]"]
        packages += ["-e", ROOT / "simulator"]
        for _, folder, _ in APPS:
            packages += ["-e", ROOT / folder]
        packages += ["playwright>=1.48"]
    else:
        packages += ["playwright>=1.48"]
    log("installing the servers into it (a minute or two, once)")
    run([layout.python, "-m", "pip", "install", "-q", *packages])
    marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))


def build_interface(folder: Path, force: bool) -> None:
    """``npm ci`` and ``npm run build`` in ``folder`` when dist is missing or older than src."""

    index = folder / "dist" / "index.html"
    if index.exists() and not force:
        newest = max(
            (path.stat().st_mtime for path in (folder / "src").rglob("*") if path.is_file()),
            default=0.0,
        )
        if index.stat().st_mtime >= newest:
            return
    npm = shutil.which("npm") or die("npm not found: install Node.js 22")
    if not (folder / "node_modules").is_dir() or force:
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=folder, stdout=subprocess.DEVNULL)
    run([npm, "run", "build"], cwd=folder, stdout=subprocess.DEVNULL)


def build_ui(force: bool) -> None:
    """ui/ first: every interface links it (file:../ui), so it is built before them."""

    folder = ROOT / "ui"
    built = folder / "dist" / "index.js"
    newest = max(
        (p.stat().st_mtime for p in (folder / "src").rglob("*") if p.is_file()), default=0.0
    )
    if built.exists() and not force and built.stat().st_mtime >= newest:
        return
    npm = shutil.which("npm") or die("npm not found: install Node.js 22")
    if not (folder / "node_modules").is_dir() or force:
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=folder, stdout=subprocess.DEVNULL)
    run([npm, "run", "build"], cwd=folder, stdout=subprocess.DEVNULL)


def build_site(layout: Layout, suite_url: str) -> None:
    run(
        [
            layout.python,
            ROOT / "site" / "build.py",
            "--out",
            layout.site,
            "--draft",
            "--noindex",
            "--demo-url",
            suite_url,
        ],
        cwd=ROOT / "site",
        stdout=subprocess.DEVNULL,
    )


# Background processes ---------------------------------------------------------------------------


def start(layout: Layout, name: str, command: list, env: dict, cwd: Path = ROOT):
    layout.logs.mkdir(parents=True, exist_ok=True)
    out = open(layout.logs / f"{name}.log", "ab")
    out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start\n".encode())
    process = subprocess.Popen(
        [str(part) for part in command],
        cwd=cwd,
        env=env,
        stdout=out,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    pids = layout.read_state().get("pids", {})
    pids[name] = process.pid
    layout.write_state(pids=pids)
    return process


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_processes(layout: Layout) -> None:
    pids = layout.read_state().get("pids", {})
    for name, pid in pids.items():
        if alive(pid):
            log(f"stopping {name} ({pid})")
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
    deadline = time.monotonic() + 20
    while any(alive(pid) for pid in pids.values()) and time.monotonic() < deadline:
        time.sleep(0.5)
    for pid in pids.values():
        if alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
    layout.write_state(pids={})


def start_site(layout: Layout, suite_url: str) -> None:
    build_site(layout, suite_url)
    env = clean_env()
    env.update(SITE_DIST=str(layout.site), SITE_DATA_DIR=str(layout.dir / "site-data"))
    # The chat stays off unless the person set a provider and key for it.
    command = [layout.python, "-m", "sitechat", "serve", "--port", layout.site_port]
    process = start(layout, "site", command, env, cwd=ROOT / "site")
    wait_for("the site", lambda: http_ok(f"http://127.0.0.1:{layout.site_port}/"), 60, process)


def clean_env() -> dict:
    """This environment without the variables of a suite or app the person may have set."""

    prefixes = ("PLANTCRAFT_", "PROCESSCRAFT_", "HISTCRAFT_", "LINKCRAFT_", "DASHCRAFT_")
    prefixes += ("ALARMCRAFT_", "MODELCRAFT_", "DOCCRAFT_", "SIMCRAFT_", "VIRTUAL_ENV")
    env = {key: value for key, value in os.environ.items() if not key.startswith(prefixes)}
    env["PATH"] = f"{Path(sys.executable).parent}:{env.get('PATH', '')}"
    return env


# Light mode -------------------------------------------------------------------------------------


def light_up(layout: Layout, args) -> None:
    if port_open(layout.port) or port_open(layout.platform_port):
        die(
            f"something already listens on {layout.port} or {layout.platform_port}: make preview-down"
        )
    ensure_venv(layout, suite=True)
    bin_dir = layout.venv / "bin"
    log("interfaces (npm ci and a build when one is missing or out of date)")
    build_ui(args.rebuild)
    for folder in ["frontend"] + [f"{app_folder}/frontend" for _, app_folder, _ in APPS]:
        build_interface(ROOT / folder, args.rebuild)

    data = layout.data
    data.mkdir(parents=True, exist_ok=True)
    admin_password = secret_file(data / "admin-password")
    visitor_file = data / "public-demo-password"
    secret_file(visitor_file, "plantcraft-demo")
    public = args.mode == "public-demo"
    zone = time_zone()

    # PlantCraft's installation scenario, as the image's (deploy/site/site.json), here.
    scenario = json.loads((ROOT / "deploy" / "site" / "site.json").read_text())
    scenario["source"]["path"] = str(ROOT / "deploy" / "site" / "no-data.csv")
    scenario["storage"]["sqlite_path"] = str(data / "processcraft" / "processcraft.sqlite3")
    (data / "processcraft").mkdir(exist_ok=True)
    (data / "site.json").write_text(json.dumps(scenario, indent=2))
    # The demo's plant map, reading the Simulator here instead of the compose service; the seed
    # reads the documents and diagrams beside it.
    demo = data / "demo"
    demo.mkdir(exist_ok=True)
    plant_map = (ROOT / "deploy" / "demo" / "plantcraft-50-loops-map.json").read_text()
    plant_map = plant_map.replace(
        "opc.tcp://plantcraft:4840/", f"opc.tcp://127.0.0.1:{OPCUA_PORT}/"
    )
    (demo / "plantcraft-50-loops-map.json").write_text(plant_map)
    for name in ("documents", "diagrams"):
        if not (demo / name).exists():
            (demo / name).symlink_to(ROOT / "deploy" / "demo" / name)

    app_urls = {
        app_id: f"http://127.0.0.1:{layout.app_port(i)}" for i, (app_id, _, _) in enumerate(APPS)
    }
    base = clean_env()
    base["PATH"] = f"{bin_dir}:{base['PATH']}"
    base.update(VIRTUAL_ENV=str(layout.venv), PLANTCRAFT_TIMEZONE=zone, PLANTCRAFT_LOG_LEVEL="INFO")
    platform_env = dict(base)
    platform_env.update(
        PLANTCRAFT_SCENARIO=str(data / "site.json"),
        PLANTCRAFT_HOST="127.0.0.1",
        PLANTCRAFT_PORT=str(layout.platform_port),
        PLANTCRAFT_WORKERS="2",
        PLANTCRAFT_BASIC_AUTH_ENABLED="true",
        PLANTCRAFT_BASIC_AUTH_USERNAME="admin",
        PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE=str(data / "admin-password"),
        PLANTCRAFT_SESSION_HTTPS_ONLY="false",
        PLANTCRAFT_DEMO_USERS="false",
        PLANTCRAFT_PUBLIC_DEMO="true" if public else "false",
        PLANTCRAFT_PUBLIC_DEMO_PASSWORD_FILE=str(visitor_file),
        PLANTCRAFT_APPS=",".join(f"{app_id}={prefix}" for app_id, _, prefix in APPS),
        HISTCRAFT_URL=f"{app_urls['histcraft']}/hist",
        PLANTCRAFT_OPS_URLS=",".join(
            f"{app_id}={app_urls[app_id]}{prefix.rstrip('/')}" for app_id, _, prefix in APPS
        ),
        PLANTCRAFT_APP_INSTALL="off",
        FORWARDED_ALLOW_IPS="127.0.0.1",
    )

    log(f"Simulator on opc.tcp://127.0.0.1:{OPCUA_PORT} (the first start writes 48 h of history)")
    (data / "simcraft").mkdir(exist_ok=True)
    simulator = start(
        layout,
        "simcraft",
        [
            bin_dir / "simcraft",
            "loops",
            "serve",
            "--endpoint",
            f"opc.tcp://127.0.0.1:{OPCUA_PORT}/plantcraft/",
            "--history-db",
            data / "simcraft" / "opcua-history.sqlite3",
            "--state-db",
            data / "simcraft" / "opcua-state.sqlite3",
        ],
        dict(base, SQLITE_TMPDIR=str(data / "simcraft")),
    )

    log("app keys")
    run(
        [layout.python, __file__, "_app-keys", data, *[app_id for app_id, _, _ in APPS]],
        env=platform_env,
    )

    log(f"PlantCraft on {layout.platform_port}")
    platform = start(
        layout, "processcraft", [layout.python, "-m", "plantcraft.api.serve"], platform_env
    )
    wait_for(
        "PlantCraft",
        lambda: http_ok(f"http://127.0.0.1:{layout.platform_port}/healthz"),
        180,
        platform,
    )

    processes = {}
    for index, (app_id, _, prefix) in enumerate(APPS):
        upper = app_id.upper()
        folder = data / app_id
        folder.mkdir(exist_ok=True)
        env = dict(base)
        env.update(
            {
                "PLANTCRAFT_URL": f"http://127.0.0.1:{layout.platform_port}",
                "PLANTCRAFT_HISTORIAN_URL": platform_env["HISTCRAFT_URL"],
                f"{upper}_ROOT_PATH": prefix.rstrip("/"),
                f"{upper}_DATA_DIR": str(folder),
                f"{upper}_HOST": "127.0.0.1",
                f"{upper}_PORT": str(layout.app_port(index)),
                "SQLITE_TMPDIR": str(folder),
                # No compute worker here: the analyses and models run in the app's own processes.
                "LINKCRAFT_COMPUTE": "local",
                "MODELCRAFT_RUNNER": "local",
            }
        )
        if app_id != "histcraft":
            env["PLANTCRAFT_APP_KEY_FILE"] = str(data / f"{app_id}-app-key")
        else:
            env.pop("PLANTCRAFT_HISTORIAN_URL")
            env["HISTCRAFT_CSV_DIRS"] = str(folder / "csv")
        command = [bin_dir / app_id, "serve", "--host", "127.0.0.1"]
        command += ["--port", layout.app_port(index)]
        processes[app_id] = start(layout, app_id, command, env)
        log(f"{app_id} on {layout.app_port(index)}{prefix}")

    proxy_routes = {prefix: app_urls[app_id] for app_id, _, prefix in APPS}
    start(
        layout,
        "proxy",
        [
            layout.python,
            __file__,
            "_proxy",
            "--port",
            layout.port,
            "--platform",
            f"http://127.0.0.1:{layout.platform_port}",
            "--routes",
            json.dumps(proxy_routes),
        ],
        base,
    )
    for index, (app_id, _, _) in enumerate(APPS):
        url = f"http://127.0.0.1:{layout.app_port(index)}/healthz"
        wait_for(app_id, lambda url=url: http_ok(url), 180, processes[app_id])
    wait_for("the proxy", lambda: http_ok(f"http://127.0.0.1:{layout.port}/healthz"), 30)
    wait_for("the Simulator", lambda: port_open(OPCUA_PORT), 300, simulator)
    suite_url = f"http://127.0.0.1:{layout.port}/"
    start_site(layout, suite_url)
    layout.write_state(
        mode="light", public=public, url=suite_url, password_file=str(data / "admin-password")
    )

    if not args.no_seed and not (data / "seeded").exists():
        log("the demo story (plantcraft demo seed: about 10 minutes, see logs/seed.log)")
        seed = [bin_dir / "plantcraft", "demo", "seed"]
        seed += ["--url", f"http://127.0.0.1:{layout.platform_port}"]
        seed += ["--password-file", data / "admin-password"]
        seed += ["--map", demo / "plantcraft-50-loops-map.json"]
        for app_id, _, prefix in APPS:
            if app_id == "modelcraft" and not shutil.which("omc"):
                # Models' story runs simulations: without OpenModelica here it has none.
                log("Models' runs skipped: no OpenModelica (omc) on this machine")
                continue
            seed += ["--app", f"{app_id}={app_urls[app_id]}{prefix.rstrip('/')}"]
        process = start(layout, "seed", seed, platform_env)
        code = process.wait()
        if code == 0:
            (data / "seeded").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            log(f"WARNING: the demo story is incomplete (exit {code}): {layout.logs / 'seed.log'}")
    print_summary(layout, admin_password)


def print_summary(layout: Layout, password: str) -> None:
    state = layout.read_state()
    print()
    print(f"  Suite  {state.get('url')}   (admin / {password})")
    if state.get("public"):
        print("         public demo: the sign-in page shows 'Enter the demo'")
    print(f"  Site   http://127.0.0.1:{layout.site_port}/")
    print(f"  Logs   {layout.logs}/")
    print("  Stop   make preview-down    Fresh data   make preview-reset")
    print()


def app_keys(folder: str, ids: list) -> None:
    """``_app-keys``: an app key per app in ``folder/<id>-app-key`` (made once, as install.sh)."""

    from plantcraft.api.runtime import scenario_from_environment
    from plantcraft.platform.workspace import Workspace

    workspace = Workspace(scenario_from_environment().storage.sqlite_path)
    for app_id in ids:
        if app_id == "histcraft":  # the Historian calls nobody: no key
            continue
        path = Path(folder) / f"{app_id}-app-key"
        if path.exists() and workspace.app_keys.verify(app_id, path.read_text().strip()):
            continue
        _, secret = workspace.app_keys.create(app_id, label="Local preview", actor="preview")
        path.write_text(secret)
        path.chmod(0o600)


# The light proxy: the suite's Caddy routes (deploy/proxy/Caddyfile) in a few lines of ASGI -------


def upstream(scope: dict, platform: str, routes: dict) -> tuple:
    """Where the light proxy sends a request, as deploy/proxy/Caddyfile does: ("redirect",
    "/link/") for a bare prefix; (url, True) for PlantCraft (with the edge header), including a
    signed-in person's page under a framed app; (url, False) for an app."""

    path = scope["path"]
    headers = {key.lower(): value for key, value in scope["headers"]}
    query = scope.get("query_string", b"")
    for prefix, target in routes.items():
        if path + "/" == prefix:
            return "redirect", prefix
        if not path.startswith(prefix):
            continue
        framed = (
            prefix in FRAMED
            and not path.startswith(prefix + "api/")
            and headers.get(b"sec-fetch-dest") == b"document"
            and b"processcraft_token=" in headers.get(b"cookie", b"")
            and b"pc-frame=off" not in query
        )
        return (platform, True) if framed else (target, False)
    return platform, True


def proxy(port: int, platform: str, routes: dict) -> None:
    import asyncio

    import httpx
    import uvicorn

    hop = {
        b"connection",
        b"keep-alive",
        b"proxy-connection",
        b"transfer-encoding",
        b"upgrade",
        b"te",
        b"trailer",
        b"host",
    }
    client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(None, connect=5.0))

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await client.aclose()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return
        target, edge = upstream(scope, platform, routes)
        if target == "redirect":
            await send(
                {
                    "type": "http.response.start",
                    "status": 308,
                    "headers": [(b"location", edge.encode())],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        headers = [(k, v) for k, v in scope["headers"] if k.lower() not in hop]
        client_ip = (scope.get("client") or ("127.0.0.1", 0))[0]
        headers += [(b"x-forwarded-for", client_ip.encode()), (b"x-forwarded-proto", b"http")]
        host = dict(scope["headers"]).get(b"host", b"127.0.0.1")
        headers += [(b"x-forwarded-host", host), (b"host", host)]
        if edge:
            headers.append((b"x-plantcraft-edge", b"1"))
        url = target + scope["raw_path"].decode("latin-1")
        if scope.get("query_string"):
            url += "?" + scope["query_string"].decode("latin-1")
        request = client.build_request(scope["method"], url, headers=headers, content=body)
        deadline = time.monotonic() + (60 if edge else 15)
        while True:  # a server being restarted refuses for a moment: keep dialling (Caddy's lb_try)
            try:
                answer = await client.send(request, stream=True)
                break
            except httpx.ConnectError:
                if time.monotonic() > deadline:
                    await send({"type": "http.response.start", "status": 502, "headers": []})
                    await send({"type": "http.response.body", "body": b"Bad gateway"})
                    return
                await asyncio.sleep(0.5)
        try:
            out = [(k, v) for k, v in answer.headers.raw if k.lower() not in hop]
            await send(
                {"type": "http.response.start", "status": answer.status_code, "headers": out}
            )
            async for chunk in answer.aiter_raw():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b""})
        finally:
            await answer.aclose()

    uvicorn.run(
        app, host=os.environ.get("PREVIEW_BIND", "127.0.0.1"), port=port, log_level="warning"
    )


# Docker mode ------------------------------------------------------------------------------------


# Images each make target builds: (make arguments, [(image, version folder)]).
def image_targets() -> list:
    platform = [
        ("processcraft", ROOT),
        ("processcraft-proxy", ROOT),
        ("processcraft-installer", ROOT),
    ]
    targets = [(["image"], platform)]
    for app_id, folder, _ in APPS:
        targets.append((["-C", folder, "image"], [(app_id, ROOT / folder)]))
    targets.append(
        (["-C", "apps/models", "runner-image"], [("modelcraft-runner", ROOT / "apps/models")])
    )
    targets.append((["simcraft-image"], [("simcraft", ROOT / "simulator")]))
    return targets


def docker(*command, capture: bool = False) -> str:
    result = subprocess.run(
        ["docker", *[str(part) for part in command]],
        check=not capture,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.DEVNULL if capture else None,
    )
    return (result.stdout or "").strip()


def image_id(name: str) -> str:
    return docker("image", "inspect", "-f", "{{.Id}}", name, capture=True)


def build_images(layout: Layout, force: bool) -> None:
    """Every image of this checkout as ``<image>:<version>-preview``; the ``<version>`` tags are
    put back on the images they named before, so another suite here keeps its own."""

    for make_args, images in image_targets():
        tags = [(name, version_of(folder)) for name, folder in images]
        if not force and all(image_id(f"{name}:{version}-preview") for name, version in tags):
            continue
        before = {name: image_id(f"{name}:{version}") for name, version in tags}
        try:
            run(
                ["make", *make_args, f"SIMCRAFT_VERSION={version_of(ROOT / 'simulator')}"], cwd=ROOT
            )
            for name, version in tags:
                docker("tag", f"{name}:{version}", f"{name}:{version}-preview")
        finally:
            for name, version in tags:
                if before[name]:
                    docker("tag", before[name], f"{name}:{version}")
                elif image_id(f"{name}:{version}"):
                    docker("rmi", "--no-prune", f"{name}:{version}", capture=True)


def pinned_images() -> list:
    import re

    text = (ROOT / "deploy" / "compose.yaml").read_text()
    return sorted(set(re.findall(r"[a-z][a-z0-9./_-]*:[^ @}]*@sha256:[0-9a-f]{64}", text)))


def docker_up(layout: Layout, args) -> None:
    if not shutil.which("docker") or not docker("info", "-f", "{{.ServerVersion}}", capture=True):
        die("Docker is not running here: start it, or use make preview-light")
    check_folder(layout)
    ensure_venv(layout, suite=False)
    build_images(layout, args.rebuild)
    for pinned in pinned_images():
        if not image_id(pinned):
            run(["docker", "pull", "-q", pinned])

    # install.sh runs from a copy of deploy/ whose versions are the preview's tags.
    versions = {
        "PLANTCRAFT_VERSION": version_of(ROOT),
        "SIMCRAFT_VERSION": version_of(ROOT / "simulator"),
    }
    for app_id, folder, _ in APPS:
        versions[f"{app_id.upper()}_VERSION"] = version_of(ROOT / folder)
    if layout.bundle.exists():
        shutil.rmtree(layout.bundle)
    shutil.copytree(ROOT / "deploy", layout.bundle, symlinks=True)
    example = []
    for line in (layout.bundle / ".env.example").read_text().splitlines():
        key = line.split("=", 1)[0]
        if key in versions:
            line = f"{key}={versions[key]}-preview"
        example.append(line)
    (layout.bundle / ".env.example").write_text("\n".join(example) + "\n")

    env_file = layout.suite / ".env"
    if not env_file.exists():
        # install.sh makes .env from .env.example only when there is none: this one first, with
        # the preview's project and port (as ci/bench/frozen.sh does).
        layout.suite.mkdir(parents=True, exist_ok=True)
        name = socket.gethostname()
        lines = []
        for line in example:
            key = line.split("=", 1)[0]
            if key == "COMPOSE_PROJECT_NAME":
                line = f"COMPOSE_PROJECT_NAME={PROJECT}"
            elif key == "PLANTCRAFT_HTTPS_PORT":
                line = f"PLANTCRAFT_HTTPS_PORT={layout.port}"
            elif key == "PLANTCRAFT_HOSTNAME":
                line = f"PLANTCRAFT_HOSTNAME=localhost {name}"
            elif key == "PLANTCRAFT_BIND_ADDRESS" and os.environ.get("PREVIEW_BIND"):
                line = f"PLANTCRAFT_BIND_ADDRESS={os.environ['PREVIEW_BIND']}"
            lines.append(line)
        env_file.write_text("\n".join(lines) + "\n")
        env_file.chmod(0o640)

    env = dict(os.environ)
    env.update(
        PLANTCRAFT_VERSION=f"{versions['PLANTCRAFT_VERSION']}-preview",
        SIMCRAFT_VERSION=f"{versions['SIMCRAFT_VERSION']}-preview",
    )
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(key, None)
    demo = "--public-demo" if args.mode == "public-demo" else "--demo"
    run(
        [
            layout.bundle / "install.sh",
            "--dev",
            "--prefix",
            layout.suite,
            "--all-apps",
            demo,
            "--yes",
        ],
        env=env,
    )
    suite_url = f"https://localhost:{layout.port}/"
    start_site(layout, suite_url)
    password_file = layout.suite / "data" / "initial-admin-password"
    layout.write_state(
        mode="docker",
        public=args.mode == "public-demo",
        url=suite_url,
        password_file=str(password_file),
    )
    password = (
        password_file.read_text().strip() if password_file.exists() else "(see install.sh above)"
    )
    print_summary(layout, password)


def docker_down(layout: Layout, purge: bool) -> None:
    installed = layout.suite / "install.sh"
    if installed.exists():
        run([installed, "--uninstall", "--prefix", layout.suite, "--yes"], cwd=layout.suite)
    if purge and layout.suite.exists():
        # Files under data/ belong to the containers' users: removed from a container.
        image = f"processcraft:{version_of(ROOT)}-preview"
        docker(
            "run",
            "--rm",
            "-u",
            "0",
            "--entrypoint",
            "rm",
            "-v",
            f"{layout.suite}:/p",
            image,
            "-rf",
            "/p/data",
        )
        shutil.rmtree(layout.suite)


# Screenshots ------------------------------------------------------------------------------------


def shots(layout: Layout) -> None:
    """``_shots`` (in the venv): the site's pages, then the suite's as the administrator."""

    from playwright.sync_api import sync_playwright

    state = layout.read_state()
    if not state.get("url"):
        die("no preview runs: make preview or make preview-light first")
    suite = state["url"].rstrip("/")
    password = Path(state["password_file"]).read_text().strip()
    layout.shots.mkdir(parents=True, exist_ok=True)
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if not executable and Path("/opt/pw-browsers/chromium").exists():
        executable = "/opt/pw-browsers/chromium"
    taken = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                executable_path=executable or None, args=["--no-proxy-server"]
            )
        except Exception:  # Playwright's own Chromium is not installed yet: once.
            run([sys.executable, "-m", "playwright", "install", "chromium"])
            browser = playwright.chromium.launch(args=["--no-proxy-server"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}, ignore_https_errors=True
        )
        context.add_init_script(
            "try { localStorage.setItem('plantcraft-ui:tours-off', '1') } catch (error) {}"
        )
        page = context.new_page()

        def shoot(url: str, name: str) -> None:
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception as error:  # a page that keeps polling never goes idle: take it anyway
                log(f"{name}: {str(error).splitlines()[0]}")
            page.wait_for_timeout(1500)
            path = layout.shots / f"{name}.png"
            page.screenshot(path=str(path))
            taken.append(path)
            log(f"{path.name}  {url}")

        for html in sorted(layout.site.glob("*.html")):
            shoot(f"http://127.0.0.1:{layout.site_port}/{html.name}", f"site-{html.stem}")
        answer = page.request.post(
            f"{suite}/api/login", data={"username": "admin", "password": password}
        )
        if not answer.ok:
            die(f"sign-in as admin failed ({answer.status})")
        for path, name in SUITE_PAGES:
            shoot(f"{suite}{path}", name)
        for app_id, _, prefix in APPS:
            shoot(f"{suite}{prefix}", f"app-{app_id}")
        browser.close()
    print(f"\n  {len(taken)} screenshots in {layout.shots}/\n")


# Status and the command line --------------------------------------------------------------------


def status(layout: Layout) -> None:
    state = layout.read_state()
    if not state:
        print("No preview here yet: make preview (Docker) or make preview-light.")
        return
    print(f"Mode {state.get('mode')}, folder {layout.dir}")
    print(f"  Suite {state.get('url')}  {'up' if port_open(layout.port) else 'down'}")
    print(
        f"  Site  http://127.0.0.1:{layout.site_port}/  {'up' if port_open(layout.site_port) else 'down'}"
    )
    for name, pid in state.get("pids", {}).items():
        print(f"  {name:12} pid {pid}  {'running' if alive(pid) else 'stopped'}")


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dev/local_preview.py", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "command",
        choices=[
            "docker",
            "light",
            "reset",
            "down",
            "status",
            "shots",
            "_proxy",
            "_app-keys",
            "_shots",
        ],
    )
    parser.add_argument("rest", nargs="*")
    parser.add_argument(
        "--dir", type=Path, default=Path(os.environ.get("PREVIEW_DIR") or DEFAULT_DIR)
    )
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PREVIEW_PORT") or DEFAULT_PORT)
    )
    parser.add_argument(
        "--mode", default=os.environ.get("MODE", ""), choices=["", "demo", "public-demo"]
    )
    parser.add_argument("--rebuild", action="store_true", help="build images or interfaces again")
    parser.add_argument("--no-seed", action="store_true", help="light mode: skip the demo story")
    parser.add_argument("--platform", help=argparse.SUPPRESS)
    parser.add_argument("--routes", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    layout = Layout(args.dir.expanduser().resolve(), args.port)

    if args.command == "_proxy":
        proxy(args.port, args.platform, json.loads(args.routes))
    elif args.command == "_app-keys":
        app_keys(args.rest[0], args.rest[1:])
    elif args.command == "_shots":
        shots(layout)
    elif args.command == "light":
        check_folder(layout)
        light_up(layout, args)
    elif args.command == "docker":
        docker_up(layout, args)
    elif args.command == "down":
        stop_processes(layout)
        if layout.read_state().get("mode") == "docker":
            docker_down(layout, purge=False)
    elif args.command == "reset":
        state = layout.read_state()
        mode = state.get("mode") or "light"
        if not args.mode and state.get("public"):
            args.mode = "public-demo"
        stop_processes(layout)
        if mode == "docker":
            docker_down(layout, purge=True)
            docker_up(layout, args)
        else:
            if layout.light.exists():
                shutil.rmtree(layout.light)
            light_up(layout, args)
    elif args.command == "status":
        status(layout)
    elif args.command == "shots":
        if not layout.python.exists():
            die("no preview here: make preview or make preview-light first")
        env = clean_env()
        return subprocess.call(
            [
                str(layout.python),
                __file__,
                "_shots",
                "--dir",
                str(layout.dir),
                "--port",
                str(layout.port),
            ],
            env=env,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
