"""The tracked files carry no leftovers of an unfinished merge."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKER = re.compile(r"^(<{7}|>{7})( |$)", re.MULTILINE)
TEXT = {".md", ".py", ".ts", ".tsx", ".toml", ".json", ".yml", ".yaml", ".sh", ".txt", ".css"}


def test_no_merge_conflict_markers():
    try:
        listed = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    found = [
        name
        for name in listed
        if Path(name).suffix in TEXT
        and (ROOT / name).is_file()
        and MARKER.search((ROOT / name).read_text(errors="replace"))
    ]
    assert not found, f"merge conflict markers in {found}"
