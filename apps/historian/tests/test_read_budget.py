"""Long reads in memory, bounded (api/read_budget.py): answers JSON at once, a shared budget."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi import HTTPException

from histcraft.api.read_budget import EncodedBatch, ReadBudget


def test_an_encoded_batch_answers_what_a_plain_one_does():
    batch = EncodedBatch()
    batch.add("a:x", "number", ["2026-10-27T00:00:00Z"], [1.5])
    batch.add("a:r", "runs", [], [], {"run_at": None})
    batch.fail("a:y", 404, "Signal a:y not found.")
    expected = {
        "series": [
            {"signal": "a:x", "kind": "number", "t": ["2026-10-27T00:00:00Z"], "v": [1.5]},
            {"signal": "a:r", "kind": "runs", "t": [], "v": [], "run_at": None},
        ],
        "errors": [{"signal": "a:y", "status": 404, "detail": "Signal a:y not found."}],
    }
    assert batch.payload() == expected
    more = {"signal": "a:z", "status": 404, "detail": "Signal a:z not found."}
    answer = json.loads(batch.response([more]).body)
    assert answer == {**expected, "errors": [*expected["errors"], more]}


def test_an_encoded_batch_keeps_the_points_budget():
    batch = EncodedBatch()
    batch.budget = 3
    batch.add("a:x", "number", ["t1", "t2"], [1, 2])
    batch.add("a:y", "number", ["t1", "t2"], [1, 2])
    answer = batch.payload()
    assert [item["signal"] for item in answer["series"]] == ["a:x"]
    assert answer["errors"][0]["signal"] == "a:y" and answer["errors"][0]["status"] == 413


def test_a_read_waits_for_room_and_runs_when_the_others_are_answered():
    budget = ReadBudget(values=100, wait_seconds=5)
    order = []
    with budget.hold() as first:
        first.take(80)

        def second() -> None:
            with budget.hold() as ticket:
                ticket.take(50)
                order.append("second")

        waiting = threading.Thread(target=second)
        waiting.start()
        time.sleep(0.2)
        assert order == [] and budget.taken == 80
        order.append("first")
    waiting.join(5)
    assert order == ["first", "second"] and budget.taken == 0


def test_a_read_larger_than_the_budget_runs_alone_and_others_get_503_after_waiting():
    budget = ReadBudget(values=100, wait_seconds=0.1)
    with budget.hold() as big:
        big.take(10_000)  # alone: it takes the whole budget
        assert budget.taken == 100
        with pytest.raises(HTTPException) as refused, budget.hold() as other:
            other.take(1)
        assert refused.value.status_code == 503
    assert budget.taken == 0
