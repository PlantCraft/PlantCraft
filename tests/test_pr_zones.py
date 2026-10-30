"""dev/pr-zones sorts a pull request's files into the zones of CONTRIBUTING.md and holds a
fork's core change to an agreed issue."""

from __future__ import annotations

import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
zones = SourceFileLoader("pr_zones", str(ROOT / "dev" / "pr-zones")).load_module()


def test_every_top_level_path_has_a_deliberate_zone():
    listing = subprocess.run(
        ["git", "ls-tree", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    paths = [
        name + "/x" if kind == "tree" else name
        for kind, name in ((line.split()[1], line.split("\t", 1)[1]) for line in listing)
    ]
    docs = {path for path in paths if zones.zone(path) == "docs"}
    # Only documents read by people fall through to "docs"; code never does.
    assert all(path.endswith(".md") or path in {"LICENSE", "NOTICE", "docs/x"} for path in docs), (
        docs
    )


def test_files_land_in_their_zone():
    assert zones.zone("plantcraft/api/app.py") == "core"
    assert zones.zone("sdk/python/plantcraft_sdk/blocks.py") == "core"
    assert zones.zone("docs/api/v1/openapi.json") == "core"
    assert zones.zone("apps/link/src/linkcraft/methods/signal/frozen.py") == "app: link"
    assert zones.zone("simulator/README.md") == "app: simulator"
    assert zones.zone("templates/app/app.toml") == "app: template"
    assert zones.zone("docs/en/getting-started.md") == "docs"
    assert zones.zone("README.md") == "docs"


def _run(paths: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "dev" / "pr-zones"), "--check"],
        input=paths, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **env}, check=False,
    )  # fmt: skip


def test_a_fork_s_core_change_needs_an_issue():
    core = "plantcraft/api/app.py\n"
    assert _run(core, PR_FORK="true", PR_BODY="Makes it faster").returncode == 1
    assert _run(core, PR_FORK="true", PR_BODY="Closes #42").returncode == 0
    assert _run(core, PR_FORK="false", PR_BODY="").returncode == 0  # the owner's own


def test_an_app_or_docs_change_from_a_fork_passes_and_mixed_zones_are_flagged():
    done = _run("apps/link/src/linkcraft/x.py\ndocs/blocks.md\n", PR_FORK="true", PR_BODY="")
    assert done.returncode == 0
    assert "**app: link**: 1 file" in done.stdout and "More than one zone" in done.stdout
