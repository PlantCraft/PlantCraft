"""Synthetic oracle: detection and false alarms on 90 signals built with known faults.

A case passes when:

- clean: the verdict is ``good`` (no false alarm from any check);
- faulty: the check that looks for the fault flags it (warning or bad), and
  the verdict is not ``good``.

The pass count is a floor in ``tests/floors.toml`` that only rises.
"""

from __future__ import annotations

import tomllib
from collections import Counter
from pathlib import Path

from linkcraft.signals.assess import assess, plan
from linkcraft.signals.models import SignalQualitySettings
from tests.oracles.signal_synthetic import COUNT, HIGH, INDEX, LOW, cases

FLOORS = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "floors.toml").read_text(encoding="utf-8")
)["oracles"]


def judge(case) -> tuple[bool, str]:
    signal = {
        "id": case.name,
        "kind": "number",
        "low": LOW,
        "high": HIGH,
        "roles": [],
        "settings": {"reference": "ref"} if case.reference is not None else {},
    }
    verdict = assess(
        {
            "signal": signal,
            "values": case.values,
            "reference": case.reference,
            "start": INDEX[0],
            "end": INDEX[COUNT - 1],
            "checks": plan(signal, SignalQualitySettings()),
        }
    )
    flagged = {
        item["check"]: item for item in verdict["checks"] if item["status"] in ("warning", "bad")
    }
    expected = case.truth["detected_by"]
    if expected is None:
        ok = verdict["status"] == "good"
        why = f"false alarm: {sorted(flagged)}" if not ok else ""
    else:
        ok = expected in flagged and verdict["status"] != "good"
        why = "" if ok else f"missed; flagged {sorted(flagged)}"
    return ok, why


def test_synthetic_oracle_meets_its_floor():
    found = cases()
    results = {case.name: judge(case) for case in found}
    passed = sum(ok for ok, _ in results.values())
    misses = Counter(name.split("-")[1] for name, (ok, _) in results.items() if not ok)
    report = "\n".join(f"{name}: {why}" for name, (ok, why) in results.items() if not ok)
    print(
        f"\nsynthetic oracle: {passed} of {len(found)} (misses by fault: {dict(misses)})\n{report}"
    )
    assert len(found) >= FLOORS["signal_synthetic_case_count"]
    assert passed >= FLOORS["signal_synthetic_cases"], report
