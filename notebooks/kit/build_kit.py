"""Build the Notebooks kits: ``python notebooks/kit/build_kit.py`` (or ``make notebook-kits``).

What a person downloads from Notebooks › Run on your computer (one double
click, no administrator, no internet):

- Windows: ``...-setup.exe`` (NSIS, built when ``makensis`` is here), for this user only;
- macOS: ``...-app.zip`` with ``PlantCraft Notebooks.app``;
- every system: the portable zip, which needs no installation at all::

    PlantCraft Notebooks/
      python/                    a portable Python 3.12 (python-build-standalone, stripped), with
                                 JupyterLab, numpy, pandas, scipy, matplotlib (the versions the
                                 browser's Pyodide has) and the plantcraft-notebook package
      examples/                  the examples PlantCraft serves, there before the first connection
      Open notebooks.<bat|command|sh>
      Install.<bat|command|sh>   registers the plantcraft-notebooks:// link (the setup does it too)
      Configure token.<bat|command|sh>
      README.txt
      kit.json                   which kit, which version

The app asks once for a connection code from Notebooks › Run on your computer (the server's
address, a token of the person's own and the fingerprint of its CA; ``plantcraft_notebook.kit``).
PlantCraft adds ``plantcraft.json`` (its address) and its local
certificate authority to the zip as it sends it (``plantcraft.notebooks.kits``); the setup and
the app are the same file for everyone. No token is ever in a kit.

Runs once, online, for every system at once on any machine (``uv`` installs each system's own
wheels from ``requirements.txt``, every file checked against its SHA-256; the Python builds are
pinned by SHA-256 in ``pins.json``). Writes ``notebooks/kit/dist/<kit id>.zip`` and
``kits.json``, the list PlantCraft reads; the bundle carries that folder as ``notebook-kits/``
(deploy/bundle.sh), an optional part.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent / "python"
PINS = json.loads((HERE / "pins.json").read_text(encoding="utf-8"))
ROOT = "PlantCraft Notebooks"
# Every entry of a zip gets this time, so the same inputs give the same zip.
STAMP = (2026, 1, 1, 0, 0, 0)
# Left out of the kits: tests and caches nobody runs from a notebook.
SKIP_DIRS = {"__pycache__", "tests", "test", "idle_test", "idlelib", "turtledemo", "ensurepip"}

WINDOWS_OPEN = """@echo off
rem PlantCraft Notebooks: JupyterLab on this computer, reading the plant as you.
cd /d "%~dp0"
set "PLANTCRAFT_KIT=%~dp0"
if not exist "python\\.unblocked" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File | Unblock-File" >nul 2>&1
  echo.> "python\\.unblocked"
)
"python\\python.exe" -m plantcraft_notebook.kit {command}
if errorlevel 1 pause
"""

UNIX_OPEN = """#!/bin/sh
# PlantCraft Notebooks: JupyterLab on this computer, reading the plant as you.
cd "$(dirname "$0")" || exit 1
PLANTCRAFT_KIT="$(pwd)"
export PLANTCRAFT_KIT
{unquarantine}exec ./python/bin/python3 -m plantcraft_notebook.kit {command}
"""

# macOS marks every file of a downloaded zip as "from the internet": once the person has opened
# this script (right click › Open, the first time), it lifts that mark from its own folder, so
# Python and its libraries load without one warning each.
MAC_UNQUARANTINE = "xattr -dr com.apple.quarantine . 2>/dev/null\n"

README = """PlantCraft Notebooks on your computer
=====================================

JupyterLab with Python 3.12, numpy, pandas, scipy and matplotlib, and the plantcraft_notebook
package, which reads the plant through PlantCraft with your own access (read-only).

1. Double-click "Install" (the installer from Notebooks > Run on your computer does this
   for you).
2. In PlantCraft, Notebooks > Run on your computer > Create a connection code, and copy it.
3. Double-click "Open notebooks" (or "Configure token") and paste the code when it asks. The
   token is kept in this computer's own vault ({vault}), never in this folder's files.
   JupyterLab opens in your browser at http://127.0.0.1, reachable from this computer only.

Your notebooks are in "PlantCraft notebooks" in your {documents}. Each time it opens, the kit
refreshes the Examples folder there and copies the notebooks PlantCraft wrote for you
("Open in a notebook" in the Historian, View or an asset) into My notebooks; it never changes a
notebook you edited. In a notebook, pc.sync() does the same.

Install any other package with: %pip install <name> (in a notebook), when this computer can reach
a package index.

{first_open}

The token expires after 90 days; the kit says so a week before. Create a new connection code
and run "Configure token" again. Revoke a token on your PlantCraft profile when you stop using it.

Kit {kit_id}, version {version}.
"""

FIRST_OPEN = {
    "windows": (
        'The first time, Windows may say "Windows protected your PC": choose More info,\n'
        "then Run anyway. The kit is not signed yet."
    ),
    "macos": (
        'The first time, macOS may say the script "cannot be opened": right-click\n'
        '"Open notebooks.command", choose Open, then Open again. The kit is not signed yet.'
    ),
    "linux": (
        "If a double click opens the script as text, run it from a terminal:\n"
        '  "./Open notebooks.sh"'
    ),
}
VAULTS = {
    "windows": "Windows Credential Manager",
    "macos": "the macOS Keychain",
    "linux": "the Secret Service, or a file only you can read",
}


def download(url: str, sha256: str, target: Path) -> Path:
    if not target.exists():
        print(f"downloading {url}", flush=True)
        partial = target.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=600) as answer, partial.open("wb") as handle:
            shutil.copyfileobj(answer, handle)
        partial.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != sha256:
        target.unlink()
        sys.exit(f"{target.name}: SHA-256 {digest}, expected {sha256}")
    return target


def uv() -> str:
    found = os.environ.get("UV") or shutil.which("uv")
    if not found:
        sys.exit("uv is needed to build the kits: pip install uv (make notebook-kits does)")
    return found


def kit_version() -> str:
    """The package's version and a digest of everything a kit is made of."""

    digest = hashlib.sha256()
    templates = HERE.parents[1] / "plantcraft" / "notebooks" / "templates.py"
    cells = HERE.parents[1] / "sdk" / "python" / "plantcraft_sdk" / "notebooks.py"
    for path in [
        HERE / "pins.json",
        HERE / "requirements.txt",
        Path(__file__),
        templates,
        cells,
    ] + sorted((PACKAGE / "plantcraft_notebook").glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    version = "0.0.0"
    for line in (PACKAGE / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            version = line.split("=", 1)[1].strip().strip('"')
    return f"{version}-{digest.hexdigest()[:8]}"


def family(target: dict) -> str:
    return target["id"].split("-", 1)[0]


def site_packages(python: Path, target: dict) -> Path:
    if family(target) == "windows":
        return python / "Lib" / "site-packages"
    return python / "lib" / f"python{PINS['python']}" / "site-packages"


def install(python: Path, target: dict, wheel: Path) -> None:
    """The packages, built for ``target``, into its Python; their data next to it, as a normal
    installation has them (JupyterLab's pages in share/jupyter, its server settings in etc)."""

    site = site_packages(python, target)
    common = [
        "--target",
        str(site),
        "--python-platform",
        target["platform"],
        "--python-version",
        PINS["python"],
        "--only-binary",
        ":all:",
        "--no-cache",
        "--quiet",
    ]
    run = [uv(), "pip", "install", *common]
    subprocess.run([*run, "--require-hashes", "-r", str(HERE / "requirements.txt")], check=True)
    subprocess.run([*run, "--no-deps", str(wheel)], check=True)
    for folder in ("share", "etc"):
        moved = site / folder
        if moved.is_dir():
            shutil.copytree(moved, python / folder, dirs_exist_ok=True)
            shutil.rmtree(moved)
    # Console scripts written for the machine that built the kit: the launchers use python -m.
    for folder in ("bin", "Scripts"):
        shutil.rmtree(site / folder, ignore_errors=True)


def launchers(kit: Path, target: dict, version: str) -> None:
    kind = family(target)
    for name, command in (
        ("Open notebooks", "open"),
        ("Install", "install"),
        ("Configure token", "token"),
    ):
        if kind == "windows":
            text = WINDOWS_OPEN.format(command=command).replace("\n", "\r\n")
            (kit / f"{name}.bat").write_bytes(text.encode("utf-8"))
            continue
        suffix = ".command" if kind == "macos" else ".sh"
        unquarantine = MAC_UNQUARANTINE if kind == "macos" else ""
        path = kit / f"{name}{suffix}"
        path.write_text(UNIX_OPEN.format(command=command, unquarantine=unquarantine))
        path.chmod(0o755)
    documents = "Documents folder" if kind != "linux" else "home folder (or Documents)"
    readme = README.format(
        vault=VAULTS[kind],
        documents=documents,
        first_open=FIRST_OPEN[kind],
        kit_id=target["id"],
        version=version,
    )
    newline = "\r\n" if kind == "windows" else "\n"
    (kit / "README.txt").write_bytes(readme.replace("\n", newline).encode("utf-8"))
    about = {"kit": target["id"], "version": version, "python": PINS["python"]}
    (kit / "kit.json").write_text(json.dumps(about, indent=2) + "\n", encoding="utf-8")


def examples(kit: Path) -> None:
    """The examples PlantCraft serves, in the kit: JupyterLab has them before the computer is
    connected (``plantcraft_notebook.kit.copy_examples``)."""

    # templates.py and the SDK's notebooks.py need only the standard library: loaded on their
    # own, without PlantCraft or the SDK's other modules.
    def load(name: str, source: Path) -> Any:
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    root = HERE.parents[1]
    load("plantcraft_sdk.notebooks", root / "sdk" / "python" / "plantcraft_sdk" / "notebooks.py")
    templates = load("plantcraft_examples", root / "plantcraft" / "notebooks" / "templates.py")

    # Examples/PlantCraft, as PlantCraft serves it; the apps' folders come with the first sync.
    folder = kit / "examples" / "PlantCraft"
    folder.mkdir(parents=True, exist_ok=True)
    for item in templates.examples():
        title, notebook = templates.example_notebook(item["id"])
        notebook["metadata"].pop("plantcraft", None)
        text = json.dumps(notebook, indent=1, sort_keys=True) + "\n"
        (folder / f"{title}.ipynb").write_text(text, encoding="utf-8")


# The Windows setup (NSIS, ``makensis``): for this user only, no administrator, no internet. It
# stops a running JupyterLab, replaces the kit, adds a Start menu entry and an uninstaller, and
# runs ``kit install`` (the plantcraft-notebooks:// link). The notebooks in Documents stay.
NSIS = r"""Unicode true
ManifestDPIAware true
RequestExecutionLevel user
SetCompressor /SOLID lzma
Name "PlantCraft Notebooks"
OutFile "@OUT@"
InstallDir "$LOCALAPPDATA\Programs\PlantCraft Notebooks"
BrandingText "PlantCraft Notebooks @VERSION@"
ShowInstDetails nevershow
!define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlantCraftNotebooks"
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section
  IfFileExists "$INSTDIR\python\python.exe" 0 +2
    nsExec::Exec '"$INSTDIR\python\python.exe" -m plantcraft_notebook.kit stop'
  RMDir /r "$INSTDIR\python"
  SetOutPath "$INSTDIR"
  File /r "@KIT@/*"
  WriteUninstaller "$INSTDIR\Uninstall PlantCraft Notebooks.exe"
  CreateShortcut "$SMPROGRAMS\PlantCraft Notebooks.lnk" "$INSTDIR\python\pythonw.exe" "-m plantcraft_notebook.kit open" "$INSTDIR\python\pythonw.exe" 0
  nsExec::Exec '"$INSTDIR\python\python.exe" -m plantcraft_notebook.kit install'
  WriteRegStr HKCU "${UNINST}" "DisplayName" "PlantCraft Notebooks"
  WriteRegStr HKCU "${UNINST}" "DisplayVersion" "@VERSION@"
  WriteRegStr HKCU "${UNINST}" "Publisher" "PlantCraft"
  WriteRegStr HKCU "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall PlantCraft Notebooks.exe"'
  WriteRegDWORD HKCU "${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST}" "NoRepair" 1
SectionEnd

Function .onInstSuccess
  IfSilent +2
    MessageBox MB_OK|MB_ICONINFORMATION "PlantCraft Notebooks is installed.$\r$\n$\r$\nIn PlantCraft, Notebooks > Run on your computer > Create a connection code, then open PlantCraft Notebooks from the Start menu and paste it."
FunctionEnd

Section "Uninstall"
  nsExec::Exec '"$INSTDIR\python\python.exe" -m plantcraft_notebook.kit uninstall'
  Delete "$SMPROGRAMS\PlantCraft Notebooks.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST}"
SectionEnd
"""

# The macOS app: a link reaches it as an Apple event (``kit.mac_app``); its script hands over to
# the kit's Python (``exec``: the same process, so the event reaches it).
MAC_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>PlantCraft Notebooks</string>
  <key>CFBundleDisplayName</key><string>PlantCraft Notebooks</string>
  <key>CFBundleIdentifier</key><string>org.processcraft.notebooks</string>
  <key>CFBundleExecutable</key><string>PlantCraft Notebooks</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>@VERSION@</string>
  <key>CFBundleVersion</key><string>@VERSION@</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>CFBundleURLTypes</key>
  <array>
    <dict>
      <key>CFBundleURLName</key><string>PlantCraft Notebooks link</string>
      <key>CFBundleURLSchemes</key><array><string>plantcraft-notebooks</string></array>
    </dict>
  </array>
</dict>
</plist>
"""
MAC_START = """#!/bin/sh
# PlantCraft Notebooks: JupyterLab on this Mac, opened from PlantCraft's page or with a double click.
contents="$(cd "$(dirname "$0")/.." && pwd)"
# Once the person allowed the app, the files it holds lose the "from the internet" mark.
xattr -dr com.apple.quarantine "$contents/.." 2>/dev/null
PLANTCRAFT_KIT="$contents/Resources/kit"
export PLANTCRAFT_KIT
exec "$PLANTCRAFT_KIT/python/bin/python3" -m plantcraft_notebook.kit mac
"""


def windows_setup(kit: Path, target: Path, version: str) -> bool:
    """The Windows setup, when ``makensis`` is on this machine (False when it is not)."""

    makensis = os.environ.get("MAKENSIS") or shutil.which("makensis")
    if not makensis:
        print(
            "makensis not found: the Windows kit is a zip only (apt install nsis, brew install makensis)"
        )
        return False
    script = target.with_suffix(".nsi")
    text = (
        NSIS.replace("@OUT@", str(target)).replace("@KIT@", str(kit)).replace("@VERSION@", version)
    )
    script.write_text(text, encoding="utf-8")
    subprocess.run([makensis, "-V2", "-INPUTCHARSET", "UTF8", str(script)], check=True)
    script.unlink()
    return True


def mac_app(kit: Path, target: Path, version: str) -> None:
    """``PlantCraft Notebooks.app`` in a zip: the kit in its Resources."""

    with tempfile.TemporaryDirectory() as work:
        app = Path(work) / "PlantCraft Notebooks.app" / "Contents"
        (app / "MacOS").mkdir(parents=True)
        (app / "Resources").mkdir()
        (app / "Info.plist").write_text(MAC_PLIST.replace("@VERSION@", version.split("-")[0]))
        start = app / "MacOS" / "PlantCraft Notebooks"
        start.write_text(MAC_START)
        start.chmod(0o755)
        shutil.copytree(kit / "python", app / "Resources" / "kit" / "python", symlinks=True)
        shutil.copytree(kit / "examples", app / "Resources" / "kit" / "examples")
        shutil.copy2(kit / "kit.json", app / "Resources" / "kit" / "kit.json")
        write_zip(Path(work) / "PlantCraft Notebooks.app", target, root="PlantCraft Notebooks.app")


def unpack(tarball: Path, into: Path) -> None:
    with tarfile.open(tarball) as archive:
        archive.extractall(into, filter="tar")


def write_zip(kit: Path, target: Path, root: str = ROOT) -> None:
    """``kit`` as ``ROOT/...`` in a zip: entries sorted and dated alike, modes kept (the Python
    binary and the launchers stay executable), links kept as links."""

    partial = target.with_suffix(".part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(kit.rglob("*")):
            relative = path.relative_to(kit)
            if any(part in SKIP_DIRS for part in relative.parts) or path.suffix == ".pyc":
                continue
            info = zipfile.ZipInfo(f"{root}/{relative.as_posix()}", STAMP)
            if path.is_symlink():
                # Kept as a link (macOS and Linux unzip them so), not a second copy of a library.
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, os.readlink(path))
                continue
            if path.is_dir():
                continue
            mode = path.stat().st_mode
            info.external_attr = (stat.S_IFREG | (0o755 if mode & 0o111 else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as source, archive.open(info, "w") as sink:
                shutil.copyfileobj(source, sink, 1 << 20)
    partial.replace(target)


def described(path: Path) -> dict:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def build_wheel(into: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(into), str(PACKAGE)],
        check=True,
    )
    return next(into.glob("plantcraft_notebook-*.whl"))


def built(folder: Path, version: str, ids: list[str]) -> bool:
    """True when ``folder`` already holds these kits at this version (nothing to build again)."""

    try:
        listing = json.loads((folder / "kits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    found = {item["id"]: item for item in listing.get("kits") or []}
    return listing.get("version") == version and all(
        kit in found and (folder / found[kit]["file"]).is_file() for kit in ids
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=HERE / "dist")
    parser.add_argument("--cache", type=Path, default=HERE / ".cache")
    parser.add_argument("--only", action="append", help="kit id (windows-x64, ...); default all")
    parser.add_argument("--version", action="store_true", help="print the kits' version and stop")
    parser.add_argument("--force", action="store_true", help="build even if these kits are there")
    args = parser.parse_args()
    version = kit_version()
    if args.version:
        print(version)
        return
    targets = [item for item in PINS["targets"] if not args.only or item["id"] in args.only]
    if not args.force and built(args.output, version, [item["id"] for item in targets]):
        print(f"kits {version} already in {args.output}")
        return
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    listing: list[dict] = []
    with tempfile.TemporaryDirectory() as work:
        wheel = build_wheel(Path(work) / "wheel")
        for target in targets:
            started = time.monotonic()
            tarball = download(
                PINS["release"] + target["file"].replace("+", "%2B"),
                target["sha256"],
                args.cache / target["file"],
            )
            kit = Path(work) / target["id"]
            unpack(tarball, kit)
            install(kit / "python", target, wheel)
            launchers(kit, target, version)
            examples(kit)
            archive = args.output / f"plantcraft-notebooks-{target['id']}.zip"
            write_zip(kit, archive)
            setup = None
            if family(target) == "windows":
                setup = args.output / f"plantcraft-notebooks-{target['id']}-setup.exe"
                setup = setup if windows_setup(kit, setup, version) else None
            elif family(target) == "macos":
                setup = args.output / f"plantcraft-notebooks-{target['id']}-app.zip"
                mac_app(kit, setup, version)
            shutil.rmtree(kit)
            item = {
                "id": target["id"],
                "system": target["system"],
                "arch": target["arch"],
                **described(archive),
            }
            if setup is not None:
                item["installer"] = described(setup)
            listing.append(item)
            took = time.monotonic() - started
            print(f"{archive.name}: {archive.stat().st_size / 1e6:.0f} MB in {took:.0f} s")
    known = args.output / "kits.json"
    if args.only and known.is_file():
        # Building one kit keeps the others already built.
        kept = [
            item for item in json.loads(known.read_text())["kits"] if item["id"] not in args.only
        ]
        listing = sorted(kept + listing, key=lambda item: item["id"])
    catalog = {"version": version, "python": PINS["python"], "kits": listing}
    known.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"kits {version} in {args.output}")


if __name__ == "__main__":
    main()
