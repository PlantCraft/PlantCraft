"""Declared events: the catalog in app.toml, the event's own fields, the fake holding apps to it."""

from __future__ import annotations

import tomllib
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from test_app_manifest import APP_TOML

from plantcraft_sdk.app_manifest import ManifestError, parse_manifest
from plantcraft_sdk.client import BadRequest
from plantcraft_sdk.events import EventCatalog, EventSpec, event_fields, parse_specs
from plantcraft_sdk.links import EventIn, LinkError
from plantcraft_sdk.server import ops
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.testing import FakePlantCraft

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

CATALOG_TOML = """
[[publishes.events]]
name = "collector.stopped"
title = "Collector stopped"
severity = "critical"
category = "system"
phase = "interval"
payload = { source = "Source id" }
rule = { when = "open", minutes = 5, priority = "critical", notify = "admins", enabled = true }

[[publishes.events]]
name = "run.failed"
title = "Run failed"
severity = "warning"
category = "run"
"""


def _specs():
    return parse_specs(tomllib.loads(CATALOG_TOML)["publishes"]["events"])


@pytest.fixture()
def fake():
    return FakePlantCraft(now=NOW)


def _service(fake):
    return fake.client(None, app="linkcraft", key="test-app-key")


def test_a_catalog_declares_names_titles_and_defaults():
    stopped, failed = _specs()
    assert stopped.name == "collector.stopped" and stopped.phase == "interval"
    assert stopped.rule is not None and stopped.rule.enabled and stopped.rule.minutes == 5
    assert failed.category == "run" and failed.rule is None
    # A bare name (the form before 2026-10-25) still declares an event.
    [bare] = parse_specs(["finding.opened"])
    assert bare.title == "finding.opened" and bare.severity == "info"


@pytest.mark.parametrize(
    ("item", "needle"),
    [
        ({"name": "Bad", "title": "x"}, "name"),
        ({"name": "a.b", "title": "x", "severity": "loud"}, "severity"),
        ({"name": "a.b", "title": "x", "payload": {"Bad Field": "x"}}, "lower case"),
        # Only a system event's rule is on in a new installation.
        (
            {"name": "a.b", "title": "x", "category": "process", "rule": {"enabled": True}},
            "system",
        ),
        ({"name": "a.b", "title": "x", "rule": {"when": "open", "minutes": 5}}, "interval"),
        ({"name": "a.b", "title": "x", "rule": {"when": "repeated"}}, "minutes"),
        ({"name": "a.b", "title": "x", "extra": 1}, "extra"),
    ],
)
def test_a_spec_outside_the_rules_is_refused(item, needle):
    with pytest.raises(ValueError, match=needle):
        parse_specs([item])


def test_a_condition_names_itself_in_key():
    with pytest.raises(ValidationError, match="key"):
        EventIn(kind="x.a.b", subject="asset:a", phase="start")
    item = EventIn(kind="x.a.b", subject="asset:a", phase="end", key="a/oscillation")
    assert item.key == "a/oscillation"


def test_event_fields_fill_from_the_spec_and_the_old_payload_severity():
    stopped, failed = _specs()
    plain = EventIn(kind="histcraft.run.failed", subject="asset:a")
    assert event_fields(plain, failed) == {
        "severity": "warning",
        "key": "",
        "phase": "instant",
        "category": "run",
    }
    old = EventIn(kind="linkcraft.x.y", subject="asset:a", payload={"severity": "Critical"})
    assert event_fields(old, None)["severity"] == "critical"
    assert event_fields(EventIn(kind="x.y.z", subject="asset:a"), None)["severity"] == "info"
    # An interval event says start or end; an instant one says neither.
    with pytest.raises(LinkError, match="start or end"):
        event_fields(EventIn(kind="h.collector.stopped", subject="app:h"), stopped)
    with pytest.raises(LinkError, match="instant"):
        event_fields(
            EventIn(kind="h.run.failed", subject="asset:a", phase="start", key="k"), failed
        )


def test_event_catalog_writes_declared_events_only():
    catalog = EventCatalog("histcraft", _specs())
    item = catalog.event(
        "collector.stopped", "app:histcraft", phase="start", key="collector", summary="Stopped"
    )
    assert item["kind"] == "histcraft.collector.stopped" and item["phase"] == "start"
    assert "severity" not in item  # the platform fills it from the catalog
    with pytest.raises(KeyError, match="collector.stoped"):
        catalog.event("collector.stoped", "app:histcraft")
    assert catalog.spec("histcraft.run.failed").title == "Run failed"
    assert catalog.spec("run.failed") is catalog.spec("histcraft.run.failed")
    assert [item["name"] for item in catalog.to_json()] == ["collector.stopped", "run.failed"]


def test_the_manifest_takes_tables_and_refuses_names_with_the_app_id():
    base = _manifest()
    manifest = parse_manifest(base)
    assert [spec.name for spec in manifest.publishes.events] == ["collector.stopped", "run.failed"]
    assert isinstance(manifest.publishes.events[0], EventSpec)
    catalog = EventCatalog.from_manifest(manifest)
    assert catalog.app == "cpmcraft" and set(catalog.specs) == {"collector.stopped", "run.failed"}
    base["publishes"]["events"][1]["name"] = "cpmcraft.run.failed"
    with pytest.raises(ManifestError, match="without the app id"):
        parse_manifest(base)


def test_the_fake_keeps_the_fields_and_holds_a_declared_app_to_its_catalog(fake):
    client = _service(fake)
    # No catalog yet: anything of the app's prefix goes, as before.
    first = client.post_event("linkcraft.anything.happened", "asset:fic-101")
    assert first["severity"] == "info" and first["phase"] == "instant" and first["key"] == ""
    receipt = client.put_event_catalog(EventCatalog("linkcraft", _specs()).to_json())
    assert receipt == {"app": "linkcraft", "events": 2}
    with pytest.raises(BadRequest, match="not in the event catalog"):
        client.post_event("linkcraft.anything.happened", "asset:fic-101")
    opened = client.post_event(
        "linkcraft.collector.stopped", "app:linkcraft", phase="start", key="collector"
    )
    assert opened["severity"] == "critical" and opened["category"] == "system"
    assert opened["subject"] == "app:linkcraft"
    client.post_event("linkcraft.collector.stopped", "app:linkcraft", phase="end", key="collector")
    assert [item["phase"] for item in client.events(key="collector")] == ["start", "end"]
    [listed] = client.event_catalog()
    assert listed["app"] == "linkcraft"
    assert listed["events"][0]["kind"] == "linkcraft.collector.stopped"


def test_another_apps_subject_is_not_an_app_subject(fake):
    with pytest.raises(BadRequest):
        _service(fake).post_event("linkcraft.x.y", "app:histcraft")


def test_the_runtime_sends_the_catalog_of_its_manifest(fake):
    runtime = PlatformRuntime()
    runtime.app_id = "linkcraft"
    runtime.service_client = _service(fake)
    runtime.send_event_catalog(_manifest(), wait=True)
    assert set(fake.links.catalogs["linkcraft"].specs) == {"collector.stopped", "run.failed"}
    # No app key: the catalog rides on GET /api/ops/metrics, for PlantCraft's monitor.
    runtime.service_client = None
    try:
        assert runtime.send_event_catalog(_manifest()) is None
        names = [spec["name"] for spec in ops.metrics("linkcraft", "0.1.0")["events"]]
        assert names == ["collector.stopped", "run.failed"]
    finally:
        ops.report_catalog(None)
    assert "events" not in ops.metrics("linkcraft", "0.1.0")


def test_declare_events_reads_a_manifest(fake):
    fake.declare_events(_manifest(), app="linkcraft")
    with pytest.raises(BadRequest):
        _service(fake).post_event("linkcraft.typo.here", "asset:fic-101")


def _manifest() -> dict:
    """The reference manifest of test_app_manifest (cpmcraft) with this catalog."""

    data = tomllib.loads(APP_TOML)
    data.setdefault("publishes", {})["events"] = tomllib.loads(CATALOG_TOML)["publishes"]["events"]
    return data
