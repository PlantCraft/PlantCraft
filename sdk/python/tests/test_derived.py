"""Derived series (``PUT /api/v1/series``): the shared rules, the client and the fake."""

from __future__ import annotations

import pytest

from plantcraft_sdk.client import BadRequest, Forbidden
from plantcraft_sdk.contract import ContractError
from plantcraft_sdk.derived import (
    MAX_DERIVED_ITEMS,
    MAX_DERIVED_VALUES,
    SCORE_UNIT,
    DerivedError,
    check_owner,
    parse_derived,
    split_derived,
)
from plantcraft_sdk.testing import FakePlantCraft

T = ["2026-10-20T06:00:00Z", "2026-10-20T07:00:00+00:00"]
HEALTH = "app-linkcraft:health.fic-101"


def _app(fake: FakePlantCraft):
    return fake.client(None, app="linkcraft", key="test-app-key")


def test_ids_and_owners():
    assert split_derived(HEALTH) == ("linkcraft", "health.fic-101")
    assert split_derived("scenario:FIC-101.PV") is None
    assert check_owner("linkcraft", HEALTH) == ("app-linkcraft", "health.fic-101")
    with pytest.raises(DerivedError) as caught:
        check_owner("histcraft", HEALTH)
    assert caught.value.status == 403


def test_items_are_checked_and_normalized():
    [item] = parse_derived([{"signal": HEALTH, "t": T, "v": [80, None]}])
    assert item.kind == "number" and item.v == [80.0, None]
    assert item.t == ["2026-10-20T06:00:00+00:00", "2026-10-20T07:00:00+00:00"]
    [mode] = parse_derived([{"signal": "app-linkcraft:mode", "t": T[:1], "v": ["AUTO"]}])
    assert mode.kind == "text"
    for body in (
        None,
        [],
        {"signal": HEALTH},
        [{"signal": "scenario:x", "t": [], "v": []}],
        [{"signal": HEALTH, "t": T, "v": [1]}],
        [{"signal": HEALTH, "t": ["yesterday"], "v": [1]}],
        [{"signal": HEALTH, "t": T[:1], "v": [float("nan")]}],
        [{"signal": HEALTH, "t": T[:1], "v": ["x"], "kind": "number"}],
        [{"signal": HEALTH, "t": T[:1], "v": [1], "subject": "nope"}],
        [{"signal": HEALTH, "t": T[:1], "v": [1], "result": "Loop Health"}],
        [{"signal": HEALTH, "t": [], "v": []}] * (MAX_DERIVED_ITEMS + 1),
        [
            {
                "signal": HEALTH,
                "t": T[:1] * (MAX_DERIVED_VALUES + 1),
                "v": [1] * (MAX_DERIVED_VALUES + 1),
            }
        ],
    ):
        with pytest.raises(ContractError):
            parse_derived(body)


def test_an_app_publishes_and_reads_back_a_derived_series():
    fake = FakePlantCraft()
    client = _app(fake)
    receipt = client.put_series(
        [
            {
                "signal": HEALTH,
                "t": T,
                "v": [80, 75.5],
                "name": "FIC-101 health",
                "unit": SCORE_UNIT,
                "subject": "asset:fic-101",
                "result": "loop_health",
            }
        ]
    )
    assert receipt == {"written": 1, "errors": []}
    [found] = client.signals(app="linkcraft")
    assert found["id"] == HEALTH and found["source"] == "app-linkcraft"
    assert (found["unit"], found["subject"], found["result"]) == (
        SCORE_UNIT,
        "asset:fic-101",
        "loop_health",
    )
    assert client.signals(subject="asset:fic-101", result="loop_health") == [found]
    assert client.signals(result="other") == []
    series = client.series(HEALTH, "2026-10-20T05:00:00Z", "2026-10-20T08:00:00Z")
    assert series["v"] == [80.0, 75.5] and series["kind"] == "number"
    # A second write at the same instant replaces the value and keeps the others.
    client.put_series([{"signal": HEALTH, "t": T[1:], "v": [70]}])
    series = client.series(HEALTH, "2026-10-20T05:00:00Z", "2026-10-20T08:00:00Z")
    assert series["v"] == [80.0, 70.0]
    assert client.signal(HEALTH)["subject"] == "asset:fic-101"


def test_only_an_app_writes_its_own_source():
    fake = FakePlantCraft()
    with pytest.raises(Forbidden):
        fake.client("admin").put_series([{"signal": HEALTH, "t": T[:1], "v": [1]}])
    with pytest.raises(Forbidden):
        _app(fake).put_series([{"signal": "app-histcraft:x", "t": T[:1], "v": [1]}])
    with pytest.raises(BadRequest):
        _app(fake).put_series([{"signal": HEALTH, "t": T, "v": [1]}])
    assert fake.derived == {}


def test_a_kind_change_is_an_item_error():
    fake = FakePlantCraft()
    client = _app(fake)
    client.put_series([{"signal": HEALTH, "t": T[:1], "v": [1]}])
    receipt = client.put_series(
        [
            {"signal": "app-linkcraft:ok", "t": T[:1], "v": [1]},
            {"signal": HEALTH, "t": T[:1], "v": ["x"]},
        ]
    )
    assert receipt["written"] == 1
    assert [(e["index"], e["status"]) for e in receipt["errors"]] == [(1, 422)]


def test_the_client_splits_long_lists_and_series():
    fake = FakePlantCraft()
    client = _app(fake)
    items = [{"signal": f"app-linkcraft:s{i}", "t": T[:1], "v": [i]} for i in range(501)]
    before = fake.requests
    assert client.put_series(items)["written"] == 501
    assert fake.requests - before == 3  # a service token, then two writes
    stamps = [f"2026-10-20T00:00:{i % 60:02d}.{i:06d}Z" for i in range(MAX_DERIVED_VALUES + 5)]
    receipt = client.put_series(
        [{"signal": "app-linkcraft:long", "t": stamps, "v": [1.0] * len(stamps)}]
    )
    assert receipt["written"] == 2
