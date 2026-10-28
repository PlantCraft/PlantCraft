"""Simulator oracle: a monitoring round over loops with known faults (``simulator_cases.py``).

The data reaches LinkCraft through ``FakePlantCraft`` and the API v1 path production uses.
Each case is a test; a case the methods get wrong today is an expected failure tied to its gap
in ``docs/gaps.md`` (strict, so a fix makes it fail until the floor is raised). The pass count
never drops below ``[oracles] simulator_cases`` in ``tests/floors.toml``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.conftest import make_runtime
from tests.oracles.simulator_cases import CASES, make_fake, unmet

FLOORS = tomllib.loads((Path(__file__).parents[1] / "floors.toml").read_text(encoding="utf-8"))

# Cases the methods get wrong today, with the reason seen and the gap that tracks it.
KNOWN_FAILURES: dict[str, str] = {}


@pytest.fixture(scope="module")
def verdicts(tmp_path_factory) -> dict[str, list[str]]:
    runtime = make_runtime(tmp_path_factory.mktemp("simulator-oracle"), make_fake())
    try:
        runtime.run_round()
        statuses = {row["loop_id"]: row["status"] for row in runtime.monitor.overview_rows()}
        found = {}
        for case in CASES:
            payload = runtime.monitor.loop_payload(case.case_id)
            results = {item["method_id"]: item for item in payload["results"]}
            found[case.case_id] = unmet(case, statuses[case.case_id], results)
        return found
    finally:
        runtime.shutdown()


@pytest.mark.parametrize(
    "case_id",
    [
        pytest.param(
            case.case_id,
            marks=pytest.mark.xfail(reason=KNOWN_FAILURES[case.case_id], strict=True),
        )
        if case.case_id in KNOWN_FAILURES
        else case.case_id
        for case in CASES
    ],
)
def test_case(verdicts, case_id):
    assert verdicts[case_id] == [], "; ".join(verdicts[case_id])


def test_pass_count_never_drops(verdicts):
    passed = sum(1 for problems in verdicts.values() if not problems)
    assert passed >= FLOORS["oracles"]["simulator_cases"], verdicts
    assert len(CASES) >= FLOORS["oracles"]["simulator_case_count"]
