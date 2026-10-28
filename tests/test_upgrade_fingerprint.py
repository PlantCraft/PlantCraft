"""The upgrade test's fingerprint (ci/upgrade/fingerprint.py): what counts as lost."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fingerprint", ROOT / "ci/upgrade/fingerprint.py")
fingerprint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fingerprint)


def _taken(lists, **extra):
    return {"lists": lists, "series": {}, "results": [], "marked": {}, **extra}


def test_a_renamed_item_keeps_answering_to_its_old_id():
    answer = [{"algorithm_id": "flow_loop", "aliases": ["control_valve", "loop_health"]}]
    assert fingerprint.ids_of(answer) == ["control_valve", "flow_loop", "loop_health"]


def test_lost_ids_series_and_counts_are_problems_but_new_items_are_not():
    before = _taken({"plantcraft.assets": ["A", "B"]}, audit_total=10)
    after = _taken({"plantcraft.assets": ["A", "C"]}, audit_total=12)
    assert fingerprint.compare(before, after) == ["plantcraft.assets: 1 gone (B)"]
    after = _taken({"plantcraft.assets": ["A", "B", "C"]}, audit_total=9)
    assert fingerprint.compare(before, after) == ["audit_total: 10 before, 9 after"]
    assert fingerprint.compare(before, _taken({}, audit_total=10)) == [
        "plantcraft.assets: answered before the upgrade, not after"
    ]


def test_a_retired_series_keeps_its_archive_and_an_older_alarm_becomes_a_rule():
    before = _taken(
        {
            "plantcraft.signals": ["app-linkcraft:FIC-1.status", "app-linkcraft:FIC-2.status"],
            "historian.points": ["11", "12"],
            "alarms.alarms": ["fic-1-low", "fic-2-low"],
        }
    )
    after = _taken(
        {
            "plantcraft.signals": [],
            "historian.points": [],
            "alarms.alarms": [],
            "alarms.rules": ["fic-1-low"],
        },
        archived=["11", "app-linkcraft:FIC-1.status"],
    )
    assert fingerprint.compare(before, after) == [
        "plantcraft.signals: 1 gone (app-linkcraft:FIC-2.status)",
        "historian.points: 1 gone (12)",
        "alarms.alarms: 1 gone (fic-2-low)",
    ]
