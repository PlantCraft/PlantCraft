"""The assistant's test battery against a model that obeys every instruction (docs/llm-battery.md).

What holds here holds whatever the model does: the key and other people's data never reach it,
nothing is written, unknown tools are refused, the limits cut before the model. A case marked
``pending:A`` is a guard the demo plan adds (front A); it fails until that guard lands, and
then this file fails until the mark is taken off (strict xfail).
"""

from __future__ import annotations

import pytest

from tests.llm_battery.cases import CASES, ask_case, judge
from tests.llm_battery.fake import Meter, ObedientModel
from tests.llm_battery.harness import installation
from tests.llm_battery.runner import Result, run_load, write_report


@pytest.fixture(scope="module")
def battery(tmp_path_factory):
    Meter.reset()
    with installation(tmp_path_factory.mktemp("battery"), ObedientModel) as found:
        yield found


def _param(case):
    marks = []
    if case.pending:
        marks.append(
            pytest.mark.xfail(
                strict=True, reason=f"guard planned in front {case.pending}, not in code yet"
            )
        )
    return pytest.param(case, id=case.id, marks=marks)


@pytest.mark.parametrize("case", [_param(case) for case in CASES if case.fake != "model"])
def test_the_code_holds_against_an_obedient_model(battery, case):
    outcome = ask_case(case, battery)
    passed, notes = judge(case, outcome, battery)
    assert passed, " | ".join(notes)


def test_every_answer_arrives_when_several_people_ask_at_once(battery):
    before = ObedientModel.latency
    ObedientModel.latency = 0.2
    try:
        results, numbers = run_load(battery, people=3, questions=2, log=lambda _line: None)
    finally:
        ObedientModel.latency = before
    assert numbers["answered"] == 6, numbers
    assert results[0].passed


def test_the_obedient_model_follows_instructions_it_reads_in_tool_results(battery):
    """The fake is only worth something if it really obeys what the plant's data says."""

    outcome = ask_case(next(case for case in CASES if case.id == "data-asset-description"), battery)
    assert outcome.tool_calls == 51  # get_asset, then the description's fifty searches
    assert "perfectly normal" in outcome.text


def test_the_report_never_carries_a_planted_secret(tmp_path):
    leaked = Result(
        "x", "leakage", "Leak", "hold", False, ["FAIL: key sk-SECRET-1 seen"], "sk-SECRET-1"
    )
    path = write_report(tmp_path, "m", [leaked], None, secrets={"model key": "sk-SECRET-1"})
    assert "sk-SECRET-1" not in path.read_text()
    assert "sk-SECRET-1" not in (tmp_path / "results.json").read_text()
