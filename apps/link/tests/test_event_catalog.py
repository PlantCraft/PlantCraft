"""The events Link writes are the ones its app.toml declares, and conditions carry their key."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from plantcraft_sdk.app_manifest import parse_manifest
from plantcraft_sdk.events import EventCatalog

from linkcraft import APP_ID
from linkcraft.api import events as schedule_events
from linkcraft.data.suite import _event_body
from linkcraft.loops import suite

ROOT = Path(__file__).resolve().parents[1]
CATALOG = EventCatalog.from_manifest(parse_manifest(tomllib.loads((ROOT / "app.toml").read_text())))


def test_every_kind_in_the_code_is_declared():
    written = {
        suite.FINDING_OPENED,
        suite.FINDING_CLOSED,
        suite.MESSAGE_OPENED,
        suite.MESSAGE_CLOSED,
        schedule_events.STATUS_CHANGED,
        schedule_events.RUN_FAILED,
        schedule_events.SCHEDULE_STALLED,
    }
    missing = sorted(kind for kind in written if CATALOG.spec(kind) is None)
    assert not missing, f"declare them in app.toml [[publishes.events]]: {missing}"
    # No other event kind is written anywhere in the code.
    found = set()
    for path in (ROOT / "src").rglob("*.py"):
        found |= set(re.findall(rf"{APP_ID}\.[a-z_]+\.[a-z_]+(?=\")", path.read_text()))
        found |= {
            f"{APP_ID}.{name}"
            for name in re.findall(r'f"\{APP_ID\}\.([a-z_]+\.[a-z_]+)"', path.read_text())
        }
    stray = sorted(kind for kind in found if CATALOG.spec(kind) is None and "blocks" not in kind)
    assert not stray, stray


def test_the_conditions_are_intervals_and_the_rest_instant():
    phases = {name: spec.phase for name, spec in CATALOG.specs.items()}
    assert phases["finding.opened"] == phases["finding.closed"] == "interval"
    assert phases["status.changed"] == phases["schedule.stalled"] == "interval"
    assert phases["run.failed"] == "instant"
    assert "output.status" not in phases  # the outputs are series: an Alarms rule reads them


def test_the_body_sent_keeps_the_event_fields():
    body = _event_body(
        {
            "kind": suite.FINDING_OPENED,
            "subject": "asset:FIC-101",
            "summary": "x",
            "severity": "warning",
            "phase": "start",
            "key": suite.condition_key("FIC-101", "stiction"),
        }
    )
    assert (body["phase"], body["key"], body["severity"]) == (
        "start",
        "FIC-101/stiction",
        "warning",
    )
    assert "phase" not in _event_body({"kind": suite.FINDING_OPENED, "subject": "asset:a"})
