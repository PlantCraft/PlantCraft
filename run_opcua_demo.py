#!/usr/bin/env python3
"""Start the Simulator and PlantCraft together, and Analytics when it is installed.

PlantCraft reads the simulated plant over OPC UA from the Simulator's 50-loop portfolio
(``simcraft loops serve``, from simulator/). When something already listens on
port 4840 the demo uses it; otherwise it starts the Simulator from the installed ``simcraft``
package. When the ``linkcraft`` command is on PATH (installed from apps/link:
loop performance and signal quality), the demo also starts it
on port 8140 with an app key, and lists it in PlantCraft's launcher (``PLANTCRAFT_APPS``).
``--app starter=http://127.0.0.1:9100/starter/`` does the same for an app of your own (one made
from ``templates/app``), so it can be tried inside the platform without building an image.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from plantcraft.cli import main as processcraft_main
from plantcraft.cli import reset_workspace

PROJECT_ROOT = Path(__file__).resolve().parent
SCENARIO = PROJECT_ROOT / "scenarios" / "opcua_demo.json"
CLIENT_ENDPOINT = "opc.tcp://127.0.0.1:4840/plantcraft/"
BIND_ENDPOINT = "opc.tcp://0.0.0.0:4840/plantcraft/"
# The Simulator's historian and state for the demo, beside PlantCraft's own var/ files.
SIMCRAFT_DATA = PROJECT_ROOT / "var" / "simcraft"
# The first start backfills 48 hours of history before the port opens.
SIMCRAFT_START_SECONDS = 300
SIMCRAFT_MISSING = """The Simulator is not installed, and nothing listens on port 4840.
The demo plant is its own product now. Install it into this Python environment:
    python -m pip install -e simulator            (the Simulator, in simulator/)
    python -m pip install simcraft-<version>-py3-none-any.whl
or start it yourself in another terminal (`simcraft loops serve`), then run this again."""


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _ensure_frontend() -> None:
    """Build the UI when it is missing or older than its sources, so one command runs everything."""

    frontend = PROJECT_ROOT / "frontend"
    index = frontend / "dist" / "index.html"
    sources = [path for path in (frontend / "src").rglob("*") if path.is_file()]
    sources += [frontend / name for name in ("index.html", "package.json", "vite.config.ts")]
    newest = max((path.stat().st_mtime for path in sources if path.exists()), default=0.0)
    if index.exists() and index.stat().st_mtime >= newest:
        return
    npm = shutil.which("npm")
    if npm is None:
        if not index.exists():
            print(
                "Interface not built and npm not found: install Node.js 22 or run 'npm ci && npm run build' in frontend/."
            )
        return
    print("Building the interface (frontend/)...")
    if not (frontend / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=frontend, check=True)
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)


def _app_key(app_id: str, data_dir: Path) -> Path:
    """An app key for the app's background work, made once and kept beside its data."""

    from plantcraft.api.runtime import PROJECT_ROOT as ROOT
    from plantcraft.config import load_scenario
    from plantcraft.platform.workspace import Workspace

    path = data_dir / f"{app_id}-app-key"
    keys = Workspace(load_scenario(SCENARIO, project_root=ROOT).storage.sqlite_path).app_keys
    if path.exists() and keys.verify(app_id, path.read_text(encoding="utf-8").strip()):
        return path
    _, secret = keys.create(app_id, label="Demo (run_opcua_demo.py)")
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(secret, encoding="utf-8")
    path.chmod(0o600)
    return path


def _start_app(
    app_id: str, url: str, processcraft_port: int, apps: list[str]
) -> subprocess.Popen | None:
    """Start ``<app id> serve`` on the port of ``url`` (``http://127.0.0.1:9100/starter/``) with
    an app key, and list it in PlantCraft's launcher; None when the command is not on PATH."""

    command = shutil.which(app_id)
    if command is None:
        print(f"{app_id} not found on PATH: not started.")
        return None
    data_dir = PROJECT_ROOT / "var" / app_id
    environment = {
        **os.environ,
        "PLANTCRAFT_URL": f"http://127.0.0.1:{processcraft_port}",
        "PLANTCRAFT_APP_KEY_FILE": str(_app_key(app_id, data_dir)),
        f"{app_id.upper()}_DATA_DIR": str(data_dir),
    }
    apps.append(f"{app_id}={url}")
    os.environ["PLANTCRAFT_APPS"] = ",".join(apps)
    print(f"{app_id}: {url}")
    port = str(urlsplit(url).port or 80)
    return subprocess.Popen([command, "serve", "--port", port], env=environment)


def _app_entry(text: str) -> tuple[str, str]:
    """``--app starter=http://127.0.0.1:9100/starter/``: an app id and its address."""

    app_id, _, url = text.partition("=")
    parts = urlsplit(url)
    if not app_id or parts.scheme != "http" or not parts.port or not parts.path.endswith("/"):
        raise argparse.ArgumentTypeError("expected id=http://127.0.0.1:<port>/<prefix>/")
    return app_id, url


def _simcraft_command() -> list[str] | None:
    """How to run ``simcraft loops serve``: the command on PATH, else the installed package."""

    command = shutil.which("simcraft")
    if command is not None:
        return [command, "loops", "serve"]
    if importlib.util.find_spec("simcraft") is not None:
        return [sys.executable, "-m", "simcraft", "loops", "serve"]
    return None


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PlantCraft demo with live control loops over OPC UA.",
    )
    parser.add_argument("--port", type=int, default=8060)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument(
        "--reset-simulator",
        action="store_true",
        help="Recreates the Simulator's 48 simulated hours and clears only its OPC UA historian.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Renews the demo: 48 simulated hours up to now and a fresh PlantCraft workspace.",
    )
    parser.add_argument("--skip-build", action="store_true", help="Does not rebuild the interface.")
    parser.add_argument("--linkcraft-port", type=int, default=8140)
    parser.add_argument(
        "--no-linkcraft",
        action="store_true",
        help="Does not start Analytics even when installed.",
    )
    parser.add_argument(
        "--app",
        action="append",
        default=[],
        type=_app_entry,
        metavar="ID=URL",
        help="Also starts an app of your own (installed with pip install -e, its command on "
        "PATH), as starter=http://127.0.0.1:9100/starter/. Repeatable.",
    )
    return parser


# The newest Python the demo is tested on. asyncua, the OPC UA library, fails on 3.15 (issue #10).
NEWEST_TESTED_PYTHON = (3, 13)
PYTHON_UNTESTED = (
    "Python {version} is newer than the demo is tested on (3.12 and 3.13). The OPC UA library\n"
    "asyncua fails on 3.15, so signals may show no values. Use Python 3.12 or 3.13:\n"
    "https://github.com/PlantCraft/PlantCraft/issues/10"
)


def python_warning(version: tuple[int, ...] = tuple(sys.version_info)) -> str | None:
    """A warning when this Python is newer than the demo is tested on, else None."""
    if tuple(version[:2]) <= NEWEST_TESTED_PYTHON:
        return None
    return PYTHON_UNTESTED.format(version=".".join(str(part) for part in version[:2]))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    warning = python_warning()
    if warning:
        print(warning, file=sys.stderr)
    if not args.skip_build:
        _ensure_frontend()
    if args.reset:
        if _port_open("127.0.0.1", 4840):
            print("Stop the Simulator server that is already running before renewing the demo.")
            return 2
        args.reset_simulator = True
        reset_workspace(SCENARIO)
    plant: subprocess.Popen | None = None
    if not _port_open("127.0.0.1", 4840):
        command = _simcraft_command()
        if command is None:
            print(SIMCRAFT_MISSING)
            return 2
        SIMCRAFT_DATA.mkdir(parents=True, exist_ok=True)
        command += [
            "--endpoint",
            BIND_ENDPOINT,
            "--history-db",
            str(SIMCRAFT_DATA / "opcua-history.sqlite3"),
            "--state-db",
            str(SIMCRAFT_DATA / "opcua-state.sqlite3"),
        ]
        if args.reset_simulator:
            command.append("--reset")
            # The regenerated history replaces what the platform had cached.
            os.environ["PLANTCRAFT_RESET_HISTORY_CACHE"] = "1"
        print("Starting the Simulator (the first start writes 48 hours of history)...")
        plant = subprocess.Popen(command, cwd=PROJECT_ROOT)
        deadline = time.monotonic() + SIMCRAFT_START_SECONDS
        while time.monotonic() < deadline:
            if plant.poll() is not None:
                return int(plant.returncode or 1)
            if _port_open("127.0.0.1", 4840):
                break
            time.sleep(0.25)
        else:
            plant.terminate()
            raise TimeoutError(
                f"The Simulator was not ready within {SIMCRAFT_START_SECONDS} seconds."
            )

    os.environ["PLANTCRAFT_OPCUA_ENDPOINT"] = CLIENT_ENDPOINT
    apps: list[str] = []
    started = [
        None
        if args.no_linkcraft
        else _start_app(
            "linkcraft", f"http://127.0.0.1:{args.linkcraft_port}/link/", args.port, apps
        )
    ]
    started += [_start_app(app_id, url, args.port, apps) for app_id, url in args.app]
    processcraft_args = [
        "--scenario",
        str(SCENARIO),
        "--port",
        str(args.port),
    ]
    if args.browser:
        processcraft_args.append("--browser")
    try:
        return processcraft_main(processcraft_args)
    finally:
        for process in started:
            _stop(process)
        _stop(plant)


if __name__ == "__main__":
    raise SystemExit(main())
