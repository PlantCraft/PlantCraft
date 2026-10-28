"""What an app adds to PlantCraft: [contributes] and [[publishes.series]] in app.toml, the body
the SDK sends when the app starts, and the fake holding it."""

from __future__ import annotations

import tomllib
from datetime import datetime, timezone

import pytest
from test_app_manifest import APP_TOML

from plantcraft_sdk.app_manifest import ManifestError, parse_manifest
from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.contributes import (
    FEATURES,
    ContributionsIn,
    StartIn,
    StartOut,
    contributions,
)
from plantcraft_sdk.server import ops
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.testing import FakePlantCraft

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

CONTRIBUTES_TOML = """
[[publishes.series]]
name = "{schedule}.{output}"
title = "Schedule outputs"
type = "number"
per = "asset"
retention = "app"

[[contributes.llm]]
id = "algorithm-draft"
title = "Draft an algorithm"
reads = "The description and the block catalog; no plant data."

[[contributes.widgets]]
id = "worst-assets"
title = "Worst assets"
size = "m"
sizes = [{ w = 4, h = 2 }, { w = 6, h = 3 }]
default = true

[contributes.search]
types = ["Loop"]

[[contributes.calendar]]
id = "reviews"
title = "Loop reviews"
visible = false

[[contributes.todo]]
id = "review-schedule"
title = "Review a schedule"

[[contributes.refs]]
kind = "protocol"
title = "Algorithm"
url = "/cpm/algorithms/{id}"

[[contributes.settings]]
key = "workers"
title = "Workers"
type = "integer"
default = 2
min = 1
max = 16

[[contributes.settings]]
key = "mode"
title = "Mode"
type = "choice"
options = ["fast", "careful"]
default = "careful"

[[contributes.setup]]
title = "Loops"
path = "/cpm/settings"
"""


def _data(extra: str = CONTRIBUTES_TOML) -> dict:
    data = tomllib.loads(APP_TOML)
    for key, value in tomllib.loads(extra).items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return data


def _problems(extra: str) -> str:
    with pytest.raises(ManifestError) as caught:
        parse_manifest(_data(extra))
    return "\n".join(caught.value.problems)


@pytest.fixture()
def fake():
    return FakePlantCraft(now=NOW)


def test_a_manifest_declares_what_it_adds():
    manifest = parse_manifest(_data())
    contributes = manifest.contributes
    assert [use.id for use in contributes.llm] == ["algorithm-draft"]
    assert contributes.llm[0].default == "default"
    assert contributes.widgets[0].default and contributes.widgets[0].sizes[1].w == 6
    assert contributes.search is not None and contributes.search.types == ["Loop"]
    assert contributes.calendar[0].visible is False
    assert contributes.settings[0].default == 2 and contributes.settings[1].options == [
        "fast",
        "careful",
    ]
    assert manifest.publishes.series[0].retention == "app"
    # An app that declares nothing adds nothing.
    bare = parse_manifest(tomllib.loads(APP_TOML))
    assert bare.contributes.llm == [] and bare.publishes.series == [] and not bare.contributes.queue


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("[[contributes.llm]]\nid = 'Draft'\ntitle = 'x'", "llm.0.id"),
        (
            "[[contributes.llm]]\nid = 'a'\ntitle = 'x'\n[[contributes.llm]]\nid = 'a'\ntitle = 'y'",
            "declared more than once: a",
        ),
        ("[contributes]\nqueue = true\ncolour = 'blue'", "unknown key"),
        ("[[contributes.refs]]\nkind = 'asset'\ntitle = 'x'\nurl = '/cpm/{id}'", "belongs to"),
        ("[[contributes.refs]]\nkind = 'tune'\ntitle = 'x'\nurl = '/cpm/tunes'", "{id}"),
        ("[[contributes.refs]]\nkind = 'tune'\ntitle = 'x'\nurl = 'https://x/{id}'", "url"),
        ("[[contributes.settings]]\nkey = 'a'\ntitle = 'x'\ntype = 'choice'", "lists its options"),
        (
            "[[contributes.settings]]\nkey = 'a'\ntitle = 'x'\ntype = 'integer'\ndefault = 'two'",
            "is a integer",
        ),
        ("[[contributes.settings]]\nkey = 'a'\ntitle = 'x'\ntype = 'text'\nmin = 1", "min and max"),
        ("[[contributes.setup]]\ntitle = 'x'\npath = '/hist/sources'", "under /cpm/"),
        ("[[publishes.series]]\nname = 'a'\ntitle = 'x'\ntype = 'image'", "series.0.type"),
        (
            "[[publishes.series]]\nname = 'a'\ntitle = 'x'\n[[publishes.series]]\nname = 'a'\n"
            "title = 'y'",
            "series declared more than once",
        ),
    ],
)
def test_a_contribution_that_breaks_a_rule_is_named(extra, message):
    assert message in _problems(extra)


TOOL = """
[[contributes.assistant.tools]]
id = "search_notes"
title = "Search the notes"
description = "The notes people wrote on the assets: use it for what was seen in the field."
[[contributes.assistant.tools.args]]
key = "query"
title = "What to find"
required = true
"""


def test_an_app_offers_the_assistant_a_tool():
    data = tomllib.loads(APP_TOML + TOOL)
    tool = parse_manifest(data).contributes.assistant.tools[0]
    assert tool.id == "search_notes" and tool.args[0].type == "text" and tool.args[0].required
    body = contributions(data)["contributes"]["assistant"]["tools"][0]
    assert body["id"] == "search_notes" and body["args"][0]["key"] == "query"
    assert "assistant_tools" in FEATURES
    # A dash is not a tool name the models accept, and a short description says nothing.
    assert "tools.0.id" in _problems(TOOL.replace('"search_notes"', '"search-notes"'))
    long = "The notes people wrote on the assets: use it for what was seen in the field."
    assert "description" in _problems(TOOL.replace(long, "Notes."))


def test_a_tool_may_be_called_with_each_question():
    asked = TOOL.replace(
        'title = "Search the notes"', 'title = "Search the notes"\nprefetch = "query"'
    )
    assert asked != TOOL
    tool = parse_manifest(tomllib.loads(APP_TOML + asked)).contributes.assistant.tools[0]
    assert tool.prefetch == "query"
    body = contributions(tomllib.loads(APP_TOML + asked))["contributes"]["assistant"]["tools"][0]
    assert body["prefetch"] == "query"
    # Only one of its own text arguments takes the question.
    assert "prefetch" in _problems(asked.replace('prefetch = "query"', 'prefetch = "text"'))


def test_the_body_is_the_same_from_a_dict_and_a_manifest():
    data = _data()
    from_dict = contributions(data)
    from_manifest = contributions(parse_manifest(data))
    assert from_dict == from_manifest
    assert from_dict["app"] == "cpmcraft" and from_dict["version"] == "0.1.0"
    assert from_dict["format"] == 1
    assert [spec["name"] for spec in from_dict["events"]] == ["finding.opened", "finding.closed"]
    assert from_dict["contributes"]["refs"][0]["kind"] == "protocol"


def test_tables_a_newer_app_declares_are_set_aside_not_refused():
    body = ContributionsIn.model_validate(
        {"app": "cpmcraft", "contributes": {"queue": True, "hologram": [{"id": "x"}]}}
    )
    assert body.contributes.queue and body.unknown == ["hologram"]


def test_the_runtime_sends_what_the_app_adds(fake):
    runtime = PlatformRuntime()
    runtime.app_id = "linkcraft"  # the app the token names, whatever app.toml says
    runtime.service_client = fake.client(None, app="linkcraft", key="test-app-key")
    runtime.send_contributions(_data(), wait=True, tries=1)
    stored = fake.links.contributions["linkcraft"]
    assert stored["contributes"]["llm"][0]["id"] == "algorithm-draft"
    assert stored["series"][0]["name"] == "{schedule}.{output}"
    # The events reach the catalog with the rest.
    assert set(fake.links.catalogs["linkcraft"].specs) == {"finding.opened", "finding.closed"}
    listed = runtime.service_client.contributions()
    assert listed["features"] == list(FEATURES)
    assert [item["app"] for item in listed["apps"]] == ["linkcraft"]
    assert runtime.service_client.features() == set(FEATURES)


def test_an_older_plantcraft_gets_the_event_catalog_alone(fake):
    class Older:
        sent: list = []

        def put_contributions(self, body):
            raise PlantCraftError("Not Found", status_code=404)

        def put_event_catalog(self, events):
            self.sent.append(events)

    runtime = PlatformRuntime()
    runtime.app_id = "cpmcraft"
    runtime.service_client = Older()
    runtime.send_contributions(_data(), wait=True, tries=1)
    [events] = Older.sent
    assert [spec["name"] for spec in events] == ["finding.opened", "finding.closed"]


def test_without_an_app_key_the_metrics_carry_them():
    runtime = PlatformRuntime()
    runtime.app_id = "cpmcraft"
    runtime.service_client = None
    try:
        assert runtime.send_contributions(_data()) is None
        answer = ops.metrics("cpmcraft", "0.1.0")
        assert answer["contributions"]["contributes"]["widgets"][0]["id"] == "worst-assets"
        assert [spec["name"] for spec in answer["events"]] == ["finding.opened", "finding.closed"]
    finally:
        ops.report_catalog(None)
        ops.report_contributions(None)
    assert "contributions" not in ops.metrics("cpmcraft", "0.1.0")


START = """
[[contributes.start]]
id = "analyze-loops"
title = "Monitor the loops"
description = "Reads the loops the import wrote and queues their first round."
open = "/link/loops"
"""


def test_an_app_offers_a_first_step_for_a_new_plant():
    data = tomllib.loads(APP_TOML + START)
    step = parse_manifest(data).contributes.start[0]
    assert step.id == "analyze-loops" and step.default and step.open == "/link/loops"
    assert contributions(data)["contributes"]["start"][0]["title"] == "Monitor the loops"
    assert "start" in FEATURES
    assert "start step declared more than once" in _problems(START + START)
    assert "start.0.open" in _problems(START.replace('"/link/loops"', '"https://x/loops"'))
    body = StartIn.model_validate(
        {
            "import_id": "7",
            "assets": [{"id": "U-100", "kind": "unit", "name": "Unit 100", "extra": 1}],
            "signals": [{"asset_id": "FIC-1001", "tag": "FIC-1001.PV", "role": "pv"}],
            "units": ["U-100"],
        }
    )
    assert body.assets[0].parent_id is None and body.signals[0].source_id == ""
    assert StartOut(summary="Done.", counts={"loops": 2}).open is None
