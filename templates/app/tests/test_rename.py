"""``make rename``: a copy of the template takes its own name everywhere, files included."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = shutil.ignore_patterns(
    "node_modules", "dist", "*.egg-info", "__pycache__", ".ruff_cache", ".pytest_cache", "var"
)


def test_rename_gives_the_copy_its_own_name_port_and_user(tmp_path):
    copy = tmp_path / "app"
    shutil.copytree(ROOT, copy, ignore=IGNORED)
    subprocess.run(
        [sys.executable, "tools/rename.py", "Logbook", "--port", "9110", "--uid", "20110"],
        cwd=copy,
        check=True,
        capture_output=True,
    )
    app = tomllib.loads((copy / "app.toml").read_text(encoding="utf-8"))
    assert (app["app"]["id"], app["app"]["name"]) == ("logbook", "LogbookCraft")
    assert (app["runtime"]["prefix"], app["runtime"]["port"], app["runtime"]["uid"]) == (
        "/logbook/",
        9110,
        20110,
    )
    assert (copy / "src" / "logbook" / "notes" / "store.py").is_file()
    assert (copy / "docs" / "help" / "logbook.md").is_file()
    left = [
        str(path.relative_to(copy))
        for path in copy.rglob("*")
        if path.is_file()
        and "vendor" not in path.parts
        and path.name not in {"rename.py", "test_rename.py", "package-lock.json"}
        and "starter" in path.read_text(encoding="utf-8", errors="ignore").lower()
    ]
    assert left == []
