"""``make sdk`` (part of ``make ci``) installs the SDK into a virtual environment only."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _check() -> str:
    found = re.search(r"define SDK_CHECK\n(.*?)\nendef", (ROOT / "Makefile").read_text(), re.S)
    assert found, "SDK_CHECK is gone from the Makefile"
    return found.group(1)


def _run(python: str, **env: str) -> int:
    clean = {key: value for key, value in os.environ.items() if key not in {"CI", "VIRTUAL_ENV"}}
    return subprocess.run(
        [python, "-I", "-c", _check()], cwd=ROOT, env={**clean, **env}, capture_output=True
    ).returncode


def test_the_sdk_of_this_tree_is_not_installed_again():
    import plantcraft_sdk

    if ROOT / "sdk" / "python" not in Path(plantcraft_sdk.__file__).resolve().parents:
        pytest.skip("this Python's plantcraft-sdk is not this tree's")
    assert _run(sys.executable) == 0


def test_a_python_outside_a_virtual_environment_is_left_alone():
    base = getattr(sys, "_base_executable", "") or ""
    if sys.prefix == sys.base_prefix or not base or not Path(base).exists():
        pytest.skip("needs a virtual environment and its base Python")
    status = _run(base)
    if status == 0:
        pytest.skip("the base Python already has this tree's plantcraft-sdk")
    assert status == 2
    assert _run(base, CI="true") == 3


def test_processcraft_asks_for_the_sdk_in_the_tree() -> None:
    """A new SDK version moves PlantCraft's pin with it, or the image and a fresh install fail."""

    import tomllib

    from packaging.specifiers import SpecifierSet

    def project(path: Path) -> dict:
        return tomllib.loads(path.read_text(encoding="utf-8"))["project"]

    version = project(ROOT / "sdk" / "python" / "pyproject.toml")["version"]
    pins = [
        d
        for d in project(ROOT / "pyproject.toml")["dependencies"]
        if d.startswith("plantcraft-sdk")
    ]
    assert len(pins) == 1
    assert version in SpecifierSet(pins[0].removeprefix("plantcraft-sdk")), (pins[0], version)
