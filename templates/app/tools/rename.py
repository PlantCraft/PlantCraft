#!/usr/bin/env python3
"""Give the starter app its own name: ``make rename NAME=Logbook [PORT=9110] [UID=20110]``.

``NAME=Logbook`` makes the app ``LogbookCraft``: id and Python package ``logbook``, prefix
``/logbook/``, settings ``LOGBOOK_*``, image ``logbook``. Every text file of the folder is
rewritten and ``src/starter`` moves to ``src/logbook``; run it once, on a fresh copy, then
``make ci``. PORT and UID must be free in PlantCraft's suite table (docs/app-standard.md,
section 7); ``plantcraft-app check`` says so when they are not.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "node_modules", "dist", "vendor", ".venv", "__pycache__", ".pytest_cache"}
TEXT = {".py", ".toml", ".md", ".ts", ".tsx", ".json", ".html", ".css", ".in", ".txt", ".yml"}
NAMED = {"Makefile", "Dockerfile", ".dockerignore", ".gitignore", "LICENSE"}


def files() -> list[Path]:
    found = []
    for path in sorted(ROOT.rglob("*")):
        if any(part in SKIP for part in path.relative_to(ROOT).parts) or not path.is_file():
            continue
        if path.suffix in TEXT or path.name in NAMED:
            found.append(path)
    return found


def rename(name: str, port: int | None, uid: int | None) -> list[str]:
    app_id = name.lower()
    words = [
        ("StarterCraft", f"{name}Craft"),
        ("STARTER", app_id.upper()),
        ("Starter", name),
        ("starter", app_id),
    ]
    changed = []
    for path in files():
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        new = text
        for old, value in words:
            new = new.replace(old, value)
        # The starter's port and user appear only as themselves (app.toml, Makefile, cli, docs).
        if (
            port is not None
            and not path.name.endswith(".lock")
            and path.name != "package-lock.json"
        ):
            new = new.replace("9100", str(port))
        if uid is not None and not path.name.endswith(".lock") and path.name != "package-lock.json":
            new = new.replace("20100", str(uid))
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))
    # Files and folders named after the app (src/starter, docs/help/starter.md), deepest first.
    named = [
        path
        for path in ROOT.rglob("*starter*")
        if not any(
            part in SKIP or part.endswith(".egg-info") for part in path.relative_to(ROOT).parts
        )
    ]
    for path in sorted(named, key=lambda path: len(path.parts), reverse=True):
        target = path.with_name(path.name.replace("starter", app_id))
        path.rename(target)
        changed.append(f"{path.relative_to(ROOT)} -> {target.relative_to(ROOT)}")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="the app's name without Craft, a capital and letters: Logbook")
    parser.add_argument("--port", type=int)
    parser.add_argument("--uid", type=int)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Z][a-z][a-z0-9]{1,24}", args.name):
        parser.error("NAME is one word with a capital and lower case letters, like Logbook")
    if args.name.lower() in {
        "processcraft",
        "plantcraft",
        "simcraft",
        "proxy",
        "installer",
        "api",
        "app",
    }:
        parser.error(f"{args.name} is kept by PlantCraft")
    if not (ROOT / "src" / "starter").is_dir():
        parser.error("the app was already renamed (there is no src/starter)")
    for line in rename(args.name, args.port, args.uid):
        print(line)
    print(f"Now {args.name}Craft ({args.name.lower()}). Next: make ci")
    return 0


if __name__ == "__main__":
    sys.exit(main())
