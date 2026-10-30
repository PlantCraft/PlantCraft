"""Build JupyterLite for PlantCraft's Notebooks: ``python notebooks/build.py`` (or ``make notebooks``).

Runs once, online, when the image is built (the ``notebooks`` stage of the Dockerfile); the
result (``notebooks/dist``, about 130 MB) ships in the image and needs no network afterwards.

1. Downloads the Pyodide distribution and the ``comm`` wheel pinned in ``notebooks/pins.json``
   and checks their SHA-256.
2. Keeps only the Pyodide packages a notebook here needs (``keep`` in the pins: numpy, pandas,
   scipy, matplotlib and what they depend on), about a fifth of the distribution.
3. Builds the ``plantcraft-notebook`` wheel from ``notebooks/python``.
4. Runs ``jupyter lite build`` (the versions are pinned in ``notebooks/requirements.txt``).
5. Says where Pyodide is and that nothing comes from PyPI, keeps the person's files under one
   name across builds, and moves the pages' inline scripts to files: the suite's
   Content-Security-Policy runs no inline script.
6. Adds ``lab/plantcraft-status.js``: "Starting Python on your computer…" while a kernel starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / "pins.json").read_text(encoding="utf-8"))
KERNEL = "@jupyterlite/pyodide-kernel-extension:kernel"
# Where a person's edits and settings live in their browser. JupyterLite names it after the page's
# path by default, and PlantCraft serves each build under a path of its own (/notebooks/lite/v/<build>/,
# plantcraft/notebooks/dist.py): one fixed name, the one the first builds had, keeps them across
# updates.
STORAGE = "JupyterLite Storage - /notebooks/lite/"


def download(url: str, sha256: str, target: Path) -> Path:
    if not target.exists():
        print(f"downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=600) as answer, target.open("wb") as handle:
            shutil.copyfileobj(answer, handle)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != sha256:
        target.unlink()
        sys.exit(f"{target.name}: SHA-256 {digest}, expected {sha256}")
    return target


def prune(source: Path, target: Path, roots: list[str]) -> list[str]:
    """Copy the Pyodide distribution with only ``roots`` and their dependencies."""

    lock = json.loads((source / "pyodide-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    names = {name.lower().replace("_", "-"): name for name in packages}
    keep: set[str] = set()
    todo = list(roots)
    while todo:
        name = names.get(todo.pop().lower().replace("_", "-"), "")
        if not name:
            sys.exit("a package to keep is not in this Pyodide")
        if name not in keep:
            keep.add(name)
            todo += packages[name].get("depends", [])
    files = {packages[name]["file_name"] for name in keep}
    target.mkdir(parents=True)
    for path in source.iterdir():
        if path.is_dir():
            shutil.copytree(path, target / path.name)
            continue
        wheel = path.name.removesuffix(".metadata")
        packaged = wheel.endswith((".whl", ".zip", ".tar")) and wheel != "python_stdlib.zip"
        if not packaged or wheel in files:
            shutil.copy2(path, target / path.name)
    lock["packages"] = {name: packages[name] for name in sorted(keep)}
    (target / "pyodide-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    return sorted(keep)


def inline_scripts(root: Path) -> int:
    """Each page's inline ``<script>`` moves to a file beside it (same code, same order)."""

    moved = 0
    for page in root.rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        found = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
        for number, body in enumerate(found):
            name = f"page-{page.stem}-{number}.js"
            (page.parent / name).write_text(body.strip() + "\n", encoding="utf-8")
            html = html.replace(f"<script>{body}</script>", f'<script src="{name}"></script>', 1)
            moved += 1
        if found:
            page.write_text(html, encoding="utf-8")
    return moved


def status_script(dist: Path) -> None:
    """JupyterLab's page says "Starting Python on your computer…" while the kernel starts."""

    name = "plantcraft-status.js"
    shutil.copy2(HERE / "lab" / name, dist / "lab" / name)
    page = dist / "lab" / "index.html"
    html = page.read_text(encoding="utf-8")
    if name not in html:
        page.write_text(html.replace("</body>", f'<script src="{name}"></script></body>', 1))


def configure(dist: Path) -> None:
    path = dist / "jupyter-lite.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    data = config["jupyter-config-data"]
    data["appName"] = "PlantCraft Notebooks"
    settings = data.setdefault("litePluginSettings", {}).setdefault(KERNEL, {})
    settings["pyodideUrl"] = "./static/pyodide/pyodide.js"
    # Offline: a package that is not here is an error, never a download from PyPI.
    settings["disablePyPIFallback"] = True
    data["contentsStorageName"] = STORAGE
    data["settingsStorageName"] = STORAGE
    # JupyterLab says it is loading while its files arrive (the first time, from the server).
    data["showLoadingIndicator"] = True
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=HERE / "dist")
    parser.add_argument("--cache", type=Path, default=HERE / ".cache")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    pyodide = PINS["pyodide"]
    tarball = download(pyodide["url"], pyodide["sha256"], args.cache / Path(pyodide["url"]).name)

    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        with tarfile.open(tarball) as archive:
            archive.extractall(work / "full", filter="data")
        kept = prune(work / "full" / "pyodide", work / "lite" / "pyodide", pyodide["keep"])
        print(f"Pyodide {pyodide['version']}: {len(kept)} packages kept", flush=True)
        pruned = work / "pyodide.tar.bz2"
        with tarfile.open(pruned, "w:bz2") as archive:
            archive.add(work / "lite" / "pyodide", arcname="pyodide")

        site = work / "site"
        (site / "pypi").mkdir(parents=True)
        for wheel in PINS["wheels"]:
            download(wheel["url"], wheel["sha256"], site / "pypi" / Path(wheel["url"]).name)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(site / "pypi"),
                str(HERE / "python"),
            ],
            check=True,
        )
        (site / "files").mkdir()
        # Every cell drawn as the notebook opens (not only those in view): find-in-page, printing
        # and the browser tests see the whole notebook. Ours are short.
        (site / "overrides.json").write_text(
            json.dumps({"@jupyterlab/notebook-extension:tracker": {"windowingMode": "none"}}),
            encoding="utf-8",
        )
        if args.output.exists():
            shutil.rmtree(args.output)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "jupyter",
                "lite",
                "build",
                "--pyodide",
                str(pruned),
                "--output-dir",
                str(args.output.resolve()),
            ],
            cwd=site,
            check=True,
        )
    configure(args.output)
    print(f"{inline_scripts(args.output)} inline scripts moved to files")
    status_script(args.output)
    print(f"built {args.output}")


if __name__ == "__main__":
    main()
