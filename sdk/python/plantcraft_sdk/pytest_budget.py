"""A pytest plugin that keeps every app's tests fast: a time budget per test and per run.

Installed with the SDK (entry point ``pytest11``), active only in a repository whose
``pyproject.toml`` has a ``[tool.plantcraft.tests]`` table (``docs/testing.md``)::

    [tool.plantcraft.tests]
    test_seconds = 10     # an unmarked test (setup + call + teardown)
    slow_seconds = 120    # a test marked @pytest.mark.slow (tests/e2e and tests/oracles are)
    suite_seconds = 120   # the whole run

A test over its budget, or a run over ``suite_seconds``, fails the run with the list, so a slow
test is made faster or marked ``slow`` on purpose, never by accident. ``make test-fast``
(``pytest -m "not slow"``) is the quick loop while working. ``PLANTCRAFT_TEST_BUDGET=off``
turns the check off (a machine busy with other work).
"""

from __future__ import annotations

import os
import time
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

DEFAULTS = {"test_seconds": 10.0, "slow_seconds": 120.0, "suite_seconds": 0.0}
# Folders whose tests are slow by nature: browser journeys and oracles on public data.
SLOW_FOLDERS = ("e2e", "oracles", "e2e_suite")


def _budget(config: pytest.Config) -> dict[str, float] | None:
    if os.environ.get("PLANTCRAFT_TEST_BUDGET", "").lower() in {"off", "0", "false"}:
        return None
    path = Path(str(config.rootpath)) / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    tool = table.get("tool") or {}
    # [tool.plantcraft.tests] before the rename to PlantCraft (2026-10-27).
    settings = (tool.get("plantcraft") or tool.get("processcraft") or {}).get("tests")
    if not isinstance(settings, dict):
        return None
    return {name: float(settings.get(name, default)) for name, default in DEFAULTS.items()}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tests in ``tests/e2e`` and ``tests/oracles`` are slow without saying so."""

    for item in items:
        parts = item.nodeid.split("::")[0].split("/")
        if any(folder in parts[:-1] for folder in SLOW_FOLDERS):
            item.add_marker(pytest.mark.slow)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "slow: a test over the fast budget on purpose (docs/testing.md)"
    )
    budget = _budget(config)
    if budget is not None and not config.option.collectonly:
        config.pluginmanager.register(Budget(budget), "processcraft-test-budget")


class Budget:
    """The time each test took, checked against the budget at the end of the run."""

    def __init__(self, budget: dict[str, float]):
        self.budget = budget
        self.spent: dict[str, float] = defaultdict(float)
        self.slow: set[str] = set()
        self.start = time.monotonic()
        self.over: list[str] = []

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        self.slow = {item.nodeid for item in items if item.get_closest_marker("slow")}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.spent[report.nodeid] += report.duration

    def check(self) -> list[str]:
        over = []
        for nodeid, seconds in sorted(self.spent.items(), key=lambda item: -item[1]):
            slow = nodeid in self.slow
            limit = self.budget["slow_seconds" if slow else "test_seconds"]
            if seconds > limit:
                kind = "slow test" if slow else "test"
                over.append(f"{nodeid}: {seconds:.1f} s (a {kind} gets {limit:g} s)")
        total = time.monotonic() - self.start
        if self.budget["suite_seconds"] and total > self.budget["suite_seconds"]:
            over.append(
                f"the whole run: {total:.0f} s (the budget is {self.budget['suite_seconds']:g} s)"
            )
        return over

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        self.over = self.check()
        if self.over and exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if not self.over:
            return
        terminalreporter.section("over the test time budget ([tool.plantcraft.tests])")
        for line in self.over:
            terminalreporter.line(line, red=True)
        terminalreporter.line(
            "Make it faster, or mark it @pytest.mark.slow if it must take that long "
            "(docs/testing.md in PlantCraft)."
        )
