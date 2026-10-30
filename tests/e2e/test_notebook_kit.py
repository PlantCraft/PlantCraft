"""The Notebooks kit end to end: an administrator offers it, a person downloads it, creates a
token, and the kit (the real one, when ``make notebook-kits`` built it) reads the plant with it
on this computer.

The page part runs with a stand-in kit; the kit itself needs ``notebooks/kit/dist`` with the
Linux kit (skipped otherwise), and Linux.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import pytest

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS")
BUILT = Path(__file__).resolve().parents[2] / "notebooks" / "kit" / "dist"


@pytest.fixture()
def shelf(tmp_path, monkeypatch):
    """The kits folder: the real one when built, else a stand-in kit for each system."""

    if (BUILT / "kits.json").is_file():
        monkeypatch.setenv("PLANTCRAFT_NOTEBOOK_KITS", str(BUILT))
        return BUILT
    folder = tmp_path / "kits"
    folder.mkdir()
    kits = []
    for kit_id, system in (
        ("linux-x64", "Linux"),
        ("macos-arm64", "macOS"),
        ("windows-x64", "Windows"),
    ):
        name = f"plantcraft-notebooks-{kit_id}.zip"
        with zipfile.ZipFile(folder / name, "w") as archive:
            archive.writestr("PlantCraft Notebooks/kit.json", json.dumps({"kit": kit_id}))
        kits.append(
            {"id": kit_id, "system": system, "arch": "x64", "file": name, "bytes": 150_000_000}
        )
    (folder / "kits.json").write_text(json.dumps({"version": "0.1.0-test", "kits": kits}))
    monkeypatch.setenv("PLANTCRAFT_NOTEBOOK_KITS", str(folder))
    return folder


def test_a_person_downloads_the_kit_and_creates_a_connection_code(page, shelf):
    assert page.request.put(
        "/api/notebooks/settings", data={"enabled": True, "kit_enabled": False}
    ).ok
    page.goto("/setup/notebooks")
    page.get_by_role("heading", name="Kit for people's computers").wait_for()
    page.get_by_role("button", name="Turn on the kit").click()
    page.get_by_role("button", name="Turn off the kit").wait_for()
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / "notebooks-kit-setup.png"), full_page=True)
    page.goto("/notebooks")
    page.get_by_role("tab", name="Run on your computer").click()
    download = page.get_by_role("link", name="Download for Linux (x64)", exact=False)
    download.wait_for()
    page.get_by_role("button", name="Create a connection code").click()
    code = page.locator(".nb-code").first
    code.wait_for()
    assert code.inner_text().startswith("pcnb1:")
    # The choice stays: the page opens on it the next time.
    page.reload()
    page.get_by_role("tab", name="Run on your computer", selected=True).wait_for()
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / "notebooks-kit.png"), full_page=True)
    answer = page.request.get(download.get_attribute("href"))
    assert answer.ok and answer.headers["content-type"] == "application/zip"


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.skipif(
    not (BUILT / "plantcraft-notebooks-linux-x64.zip").is_file(), reason="make notebook-kits"
)
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the Linux kit")
def test_the_linux_kit_reads_the_plant_and_opens_jupyterlab(page, shelf, tmp_path, server):
    assert page.request.put(
        "/api/notebooks/settings", data={"enabled": True, "kit_enabled": True}
    ).ok
    signal = page.request.get("/api/v1/signals").json()[0]["id"]
    made = page.request.post("/api/notebooks", data={"kind": "series", "signals": [signal]}).json()
    token = page.request.post("/api/notebooks/token").json()["token"]
    # The browser's session, outside Playwright: its protocol is slow for 180 MB.
    cookies = "; ".join(f"{item['name']}={item['value']}" for item in page.context.cookies())
    request = urllib.request.Request(
        f"{server}/api/notebooks/kits/linux-x64.zip", headers={"Cookie": cookies}
    )
    archive = tmp_path / "kit.zip"
    with urllib.request.urlopen(request, timeout=120) as answer, archive.open("wb") as sink:
        shutil.copyfileobj(answer, sink)
    subprocess.run(["unzip", "-q", str(archive), "-d", str(tmp_path)], check=True, timeout=120)
    home = tmp_path / "PlantCraft Notebooks"
    assert json.loads((home / "plantcraft.json").read_text())["url"] == server
    python = home / "python" / "bin" / "python3"
    work = tmp_path / "work"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PLANTCRAFT_KIT": str(home),
        "PLANTCRAFT_NOTEBOOK_FOLDER": str(work),
        # No desktop session here: the kit keeps the token in a file only its owner reads.
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
    }
    keep = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            f"from plantcraft_notebook import kit; print(kit.save_token({server!r}, {token!r}))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert keep.stdout.strip() == "file"
    synced = subprocess.run(
        [str(python), "-I", "-m", "plantcraft_notebook.kit", "sync"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert synced.returncode == 0, synced.stderr
    assert (work / "My notebooks" / made["name"]).is_file()
    assert len(list((work / "Examples").glob("*.ipynb"))) >= 5
    # The notebook PlantCraft wrote runs in the kit's own Python, reading the plant.
    code = (
        "import plantcraft_notebook as pc, pandas, scipy, matplotlib; "
        f"frame = pc.series([{signal!r}], '2000-01-01', 'now', step=3600); "
        "print(pc.me()['username'], len(frame.columns))"
    )
    read = subprocess.run(
        [str(python), "-I", "-c", code],
        env={**env, "PLANTCRAFT_URL": server},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert read.returncode == 0, read.stderr
    assert read.stdout.split() == ["admin", "1"]
    port = _port()
    lab = subprocess.Popen(
        [
            str(python),
            "-I",
            "-m",
            "jupyterlab",
            "--allow-root",
            "--ServerApp.ip=127.0.0.1",
            f"--ServerApp.port={port}",
            f"--ServerApp.root_dir={work}",
            "--ServerApp.open_browser=False",
            "--IdentityProvider.token=e2e",
            "--LabApp.extension_manager=readonly",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 60
        while True:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/contents/My%20notebooks?token=e2e", timeout=5
                ) as found:
                    listing = json.loads(found.read())
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.5)
        assert made["name"] in [item["name"] for item in listing["content"]]
    finally:
        lab.terminate()
        lab.wait(timeout=20)


@pytest.mark.skipif(
    not (BUILT / "plantcraft-notebooks-linux-x64.zip").is_file(), reason="make notebook-kits"
)
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the Linux kit")
def test_connect_this_computer_then_open_a_notebook_from_plantcraft(page, shelf, tmp_path, server):
    """no command and no token to copy. The page's links reach the installed
    app, which connects with a one-time code and opens the notebook in its JupyterLab."""

    assert page.request.put(
        "/api/notebooks/settings", data={"enabled": True, "kit_enabled": True}
    ).ok
    signal = page.request.get("/api/v1/signals").json()[0]["id"]
    made = page.request.post("/api/notebooks", data={"kind": "series", "signals": [signal]}).json()
    subprocess.run(
        ["unzip", "-q", str(BUILT / "plantcraft-notebooks-linux-x64.zip"), "-d", str(tmp_path)],
        check=True,
        timeout=120,
    )
    home = tmp_path / "PlantCraft Notebooks"
    python = home / "python" / "bin" / "python3"
    opened = tmp_path / "opened.txt"
    browser = tmp_path / "browser.sh"
    browser.write_text(f'#!/bin/sh\necho "$1" >> {opened}\n')
    browser.chmod(0o755)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "share"),
        "PLANTCRAFT_APP_FOLDER": str(tmp_path / "app"),
        "PLANTCRAFT_NOTEBOOK_FOLDER": str(tmp_path / "work"),
        "PLANTCRAFT_ASSUME_YES": "1",
        "BROWSER": str(browser),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
    }

    def kit(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(python), "-I", "-m", "plantcraft_notebook.kit", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    installed = kit("install")
    assert installed.returncode == 0, installed.stderr
    assert (tmp_path / "share" / "applications" / "plantcraft-notebooks-link.desktop").is_file()
    assert len(list((tmp_path / "work" / "Examples").glob("*.ipynb"))) >= 5
    link = page.request.post("/api/notebooks/pair").json()["link"]
    connected = kit("link", link)
    assert connected.returncode == 0, connected.stdout + connected.stderr
    assert "Connected to" in connected.stdout
    # The same link again: its code worked once.
    assert kit("link", link).returncode == 1
    query = urllib.parse.urlencode({"server": server, "notebook": made["name"]})
    try:
        shown = kit("link", f"plantcraft-notebooks://open?{query}")
        assert shown.returncode == 0, shown.stdout + shown.stderr
        address = opened.read_text().split()[-1]
        assert address.startswith("http://127.0.0.1:")
        assert urllib.parse.quote(f"My notebooks/{made['name']}") in address
        assert (tmp_path / "work" / "My notebooks" / made["name"]).is_file()
        base, _, token = address.partition("?token=")
        root = base.split("/lab/")[0]
        with urllib.request.urlopen(f"{root}/custom/custom.css?token={token}", timeout=10) as css:
            assert "On your computer" in css.read().decode()
        # Opening again reuses the JupyterLab that runs.
        again = kit("link", f"plantcraft-notebooks://open?{query}")
        assert again.returncode == 0
        assert opened.read_text().split()[-1].split("?token=")[1] == token
    finally:
        kit("stop")
