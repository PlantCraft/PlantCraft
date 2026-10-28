"""The previous SDK release still works with this PlantCraft (scale review E3).

Apps in the field run the SDK they were built with, so PlantCraft must keep serving the one
before the current SDK. This starts PlantCraft on a local port and runs, in another Python
with only that older SDK, the calls a suite app makes: its service token, identity, the plant,
series, results, events and the audit log. The older SDK is the newest wheel older than
``plantcraft_sdk.__version__`` in ``tests/contract/previous-sdk/`` (the SDK of the last
release, kept there at each release) or in ``apps/*/vendor``.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import httpx
import pytest
import uvicorn

import plantcraft_sdk
from processcraft.api.app import create_app

ROOT = Path(__file__).resolve().parents[2]
ADMIN, PASSWORD = "root", "root-password-123"


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


# The SDK's import name: plantcraft_sdk, or the one it had before the rename (2026-10-27).
WHEEL = re.compile(r"([a-z]+craft_sdk)-([0-9.]+)-")


def _previous_wheel() -> tuple[Path, str] | None:
    current = _version(plantcraft_sdk.__version__)
    found = {}
    wheels = [
        *(ROOT / "tests" / "contract" / "previous-sdk").glob("*craft_sdk-*.whl"),
        *ROOT.glob("apps/*/vendor/*craft_sdk-*-py3-none-any.whl"),
    ]
    for wheel in wheels:
        match = WHEEL.match(wheel.name)
        if match and _version(match.group(2)) < current:
            found[_version(match.group(2))] = (wheel, match.group(1))
    return found[max(found)] if found else None


CALLS = r"""
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
sdk = importlib.import_module(sys.argv[4])
client_module = importlib.import_module(sys.argv[4] + ".client")
Client = next(getattr(client_module, n) for n in dir(client_module) if n.endswith("CraftClient"))
url, key = sys.argv[2], sys.argv[3]
client = Client(url, app="linkcraft", key=key)
seen = {"version": sdk.__version__, "sdk": sdk.__file__}
seen["me"] = client.me()["username"]
seen["apps"] = sorted(app["id"] for app in client.apps())
seen["time_zone"] = client.installation_time_zone()
assets = client.assets()
seen["assets"] = len(assets)
signals = client.signals()
seen["signals"] = len(signals)
signal = signals[0]["id"]
seen["series"] = sorted(client.series(signal, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"))
seen["value"] = sorted(client.value(signal))
seen["audit"] = sorted(client.audit("checked", "sdk-previous"))
item = {"subject": f"signal:{signal}", "kind": "check", "status": "ok", "summary": "ok"}
seen["results"] = client.put_results([item]).get("errors", [])
seen["events"] = len(client.events())
print(json.dumps(seen))
"""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def plantcraft(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    secret = tmp_path / "admin.secret"
    secret.write_text(PASSWORD)
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(tmp_path / "scenario.json"))
    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/,histcraft=/hist/")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", ADMIN)
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 60
    while not server.started:
        assert time.monotonic() < deadline, "PlantCraft did not start"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=30)


def test_the_previous_sdk_runs_a_suite_app_against_this_plantcraft(plantcraft, tmp_path):
    previous = _previous_wheel()
    assert previous is not None, "keep the previous SDK in tests/contract/previous-sdk/"
    wheel, module = previous
    folder = tmp_path / "previous-sdk"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(folder)
    with httpx.Client(base_url=plantcraft) as admin:
        assert admin.post("/api/login", json={"username": ADMIN, "password": PASSWORD}).is_success
        created = admin.post("/api/app-keys", json={"app_id": "linkcraft", "label": "N-1"})
        assert created.status_code == 201, created.text
    script = tmp_path / "calls.py"
    script.write_text(CALLS)
    done = subprocess.run(
        [sys.executable, "-I", str(script), str(folder), plantcraft, created.json()["key"], module],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert seen["sdk"].startswith(str(folder))
    assert _version(seen["version"]) < _version(plantcraft_sdk.__version__)
    assert seen["me"] == "app:linkcraft"
    assert "linkcraft" in seen["apps"]
    assert seen["assets"] > 0 and seen["signals"] > 0
    assert seen["results"] == [] and seen["audit"]
