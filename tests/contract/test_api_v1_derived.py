"""API v1 derived series (docs/api-v1.md, "Derived series"), local data layer (no Historian).

An app's service token writes computed series to ``app-<app id>``; they are signals like the
others: listed with ``app``, ``subject`` and ``result`` (and filtered by them), read through
the series, batch and value routes. ``FakePlantCraft`` answers the same shapes.
"""

from __future__ import annotations

import pandas as pd
import pytest

from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.testing import FakePlantCraft
from tests.contract.test_api_v1 import SIGNAL_FIELDS, _app_key, _as, _auth, _rt

DERIVED_FIELDS = SIGNAL_FIELDS | {"app", "subject", "result", "managed_by", "retention_days"}
HEALTH = "app-linkcraft:health.pv"
T = ["2026-10-19T06:00:00Z", "2026-10-19T07:00:00Z", "2026-10-19T08:00:00Z"]
WINDOW = {"start": "2026-10-19T05:00:00Z", "end": "2026-10-19T09:00:00Z"}


def _service(client, app_id: str = "linkcraft") -> dict[str, str]:
    key = _app_key(client, app_id)["key"]
    grant = client.post("/api/v1/auth/service-token", json={"app": app_id, "key": key})
    return _auth(grant.json()["token"])


def _health(**fields) -> dict:
    return {
        "signal": HEALTH,
        "t": T,
        "v": [80, 75.5, None],
        "name": "PV loop health",
        "unit": "/100",
        "subject": "asset:x",
        "result": "loop_health",
        **fields,
    }


def test_an_app_writes_a_derived_series_and_everyone_reads_it_back(central):
    answer = central.put("/api/v1/series", json=[_health()], headers=_service(central))
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"written": 1, "errors": []}
    reader = _as(central, "op")
    listed = central.get("/api/v1/signals", params={"app": "linkcraft"}, headers=reader).json()
    assert [item["id"] for item in listed] == [HEALTH]
    [signal] = listed
    assert set(signal) == DERIVED_FIELDS
    assert signal["source"] == "app-linkcraft" and signal["kind"] == "number"
    assert (signal["unit"], signal["subject"], signal["result"]) == (
        "/100",
        "asset:x",
        "loop_health",
    )
    for query in ({"subject": "asset:x"}, {"result": "loop_health"}, {"q": "loop health"}):
        assert central.get("/api/v1/signals", params=query, headers=reader).json() == listed
    assert central.get("/api/v1/signals", params={"app": "other"}, headers=reader).json() == []
    everything = central.get("/api/v1/signals", headers=reader).json()
    assert HEALTH in {item["id"] for item in everything}
    plant = next(item for item in everything if item["id"] == "scenario:pv")
    assert set(plant) == SIGNAL_FIELDS  # plant signals keep their shape
    assert central.get(f"/api/v1/signals/{HEALTH}", headers=reader).json() == signal
    series = central.get(f"/api/v1/signals/{HEALTH}/series", params=WINDOW, headers=reader).json()
    assert series["v"] == [80.0, 75.5] and series["t"][0] == "2026-10-19T06:00:00+00:00"
    gridded = central.get(
        f"/api/v1/signals/{HEALTH}/series", params={**WINDOW, "step": 3600}, headers=reader
    ).json()
    assert gridded["v"] == [None, 80.0, 75.5, None]
    batch = central.post(
        "/api/v1/series", json={"signals": [HEALTH, "pv"], **WINDOW}, headers=reader
    ).json()
    assert [item["signal"] for item in batch["series"]] == [HEALTH, "pv"]
    value = central.get(f"/api/v1/signals/{HEALTH}/value", headers=reader).json()
    assert value["value"] == 75.5 and value["at"] == "2026-10-19T07:00:00+00:00"


def test_writes_replace_values_at_the_same_instant_and_keep_the_rest(central):
    headers = _service(central)
    central.put("/api/v1/series", json=[_health()], headers=headers)
    central.put(
        "/api/v1/series", json=[{"signal": HEALTH, "t": T[1:2], "v": [60]}], headers=headers
    )
    series = central.get(
        f"/api/v1/signals/{HEALTH}/series", params=WINDOW, headers=_as(central, "op")
    ).json()
    assert series["v"] == [80.0, 60.0]
    signal = central.get(f"/api/v1/signals/{HEALTH}", headers=_as(central, "op")).json()
    assert signal["unit"] == "/100" and signal["result"] == "loop_health"  # kept


def test_text_series_and_kind_conflicts(central):
    headers = _service(central)
    mode = {"signal": "app-linkcraft:mode.pv", "t": T[:2], "v": ["AUTO", "MAN"]}
    answer = central.put("/api/v1/series", json=[mode, _health()], headers=headers).json()
    assert answer == {"written": 2, "errors": []}
    clash = {"signal": HEALTH, "t": T[:1], "v": ["AUTO"]}
    answer = central.put("/api/v1/series", json=[mode, clash], headers=headers).json()
    assert answer["written"] == 1
    assert [(e["index"], e["signal"], e["status"]) for e in answer["errors"]] == [(1, HEALTH, 422)]
    series = central.get(
        "/api/v1/signals/app-linkcraft:mode.pv/series", params=WINDOW, headers=_as(central, "op")
    ).json()
    assert series["kind"] == "text" and series["v"] == ["AUTO", "MAN"]


def test_only_an_apps_service_token_writes_and_only_its_own_source(central):
    for username in ("eng", "root"):
        answer = central.put("/api/v1/series", json=[_health()], headers=_as(central, username))
        assert answer.status_code == 403, username
    answer = central.put("/api/v1/series", json=[_health()])
    assert answer.status_code == 401
    other = _service(central, "histcraft")
    answer = central.put("/api/v1/series", json=[_health()], headers=other)
    assert answer.status_code == 403 and "app-histcraft" in answer.json()["detail"]
    mixed = [{"signal": "app-histcraft:ok", "t": T[:1], "v": [1]}, _health()]
    assert central.put("/api/v1/series", json=mixed, headers=other).status_code == 403
    assert _rt(central).platform.derived.signals() == []  # nothing written


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"signal": HEALTH, "t": T, "v": [1, 2, 3]},
        [{"signal": HEALTH, "t": T, "v": [1]}],
        [{"signal": HEALTH, "t": ["tomorrow"], "v": [1]}],
        [{"signal": "pv", "t": T[:1], "v": [1]}],
        [{"signal": HEALTH, "t": T[:1], "v": [{"a": 1}]}],
        [{"signal": HEALTH, "t": T[:1], "v": [1], "subject": "loop 7"}],
        [{"signal": HEALTH, "t": T[:1], "v": [1], "result": "Loop-Health"}],
        [{"signal": HEALTH, "t": T[:1], "v": [1]}] * 501,
        [{"signal": HEALTH, "t": T[:1] * 100_001, "v": [1] * 100_001}],
    ],
)
def test_bodies_outside_the_contract_are_a_422_and_write_nothing(central, body):
    answer = central.put("/api/v1/series", json=body, headers=_service(central))
    assert answer.status_code == 422, answer.text
    assert _rt(central).platform.derived.signals() == []


def test_non_finite_numbers_are_a_422(central):
    headers = {**_service(central), "content-type": "application/json"}
    body = '[{"signal": "app-linkcraft:x", "t": ["2026-10-19T06:00:00Z"], "v": [NaN]}]'
    assert central.put("/api/v1/series", content=body, headers=headers).status_code == 422


def test_the_sdk_writes_through_processcraft_and_the_fake_answers_the_same(central):
    key = _app_key(central)["key"]
    client = PlantCraftClient("http://testserver", app="linkcraft", key=key, http_client=central)
    assert client.put_series([_health()]) == {"written": 1, "errors": []}
    [real] = client.signals(app="linkcraft")
    fake = FakePlantCraft()
    other = fake.client(None, app="linkcraft", key="test-app-key")
    assert other.put_series([_health()]) == {"written": 1, "errors": []}
    [mirror] = other.signals(app="linkcraft")
    assert mirror == real
    assert other.series(HEALTH, WINDOW["start"], WINDOW["end"]) == client.series(
        HEALTH, WINDOW["start"], WINDOW["end"]
    )


def test_a_derived_signal_can_be_the_subject_of_a_result(central):
    headers = _service(central)
    central.put("/api/v1/series", json=[_health()], headers=headers)
    result = {"subject": f"signal:{HEALTH}", "kind": "loop_health", "status": "ok", "score": 75.5}
    answer = central.put("/api/v1/results", json=[result], headers=headers).json()
    assert answer == {"saved": 1, "errors": []}


def test_a_grid_holds_values_alike_in_processcraft_and_the_fake(central):
    """Step-hold (docs/api-v1.md, "Series"): held from the first sample, a null ends it."""

    times = ["06:02", "06:07", "06:23", "06:41", "06:52"]
    values = [50, 55, 60, None, 65]
    item = _health(t=[f"2026-10-19T{hhmm}:00Z" for hhmm in times], v=values)
    assert central.put("/api/v1/series", json=[item], headers=_service(central)).status_code == 200
    window = {"start": "2026-10-19T05:50:00Z", "end": "2026-10-19T07:00:00Z", "step": 300}
    served = central.get(
        f"/api/v1/signals/{HEALTH}/series", params=window, headers=_as(central, "op")
    ).json()
    expected = [None, None, 50.0, 55.0, 55.0, 55.0, 60.0, 60.0, 60.0, 60.0, None, None, 65.0, 65.0]
    assert served["v"] == expected
    given = pd.Series(
        [float("nan") if value is None else float(value) for value in values],
        index=pd.to_datetime(item["t"], utc=True),
    )
    fake = FakePlantCraft(series={"fake:FIC-101.SP": given}).client("engineer")
    mirrored = fake.series("fake:FIC-101.SP", window["start"], window["end"], step=300)
    assert (mirrored["t"], mirrored["v"]) == (served["t"], served["v"])


def test_a_derived_series_carries_its_description(central):
    headers = _service(central)
    meaning = "Loop health from 0 to 100 (100 is best).\nWritten once per run."
    central.put("/api/v1/series", json=[_health(description=meaning)], headers=headers)
    reader = _as(central, "op")
    signal = central.get(f"/api/v1/signals/{HEALTH}", headers=reader).json()
    assert signal["description"] == meaning
    central.put("/api/v1/series", json=[{"signal": HEALTH, "t": T[2:], "v": [70]}], headers=headers)
    assert central.get(f"/api/v1/signals/{HEALTH}", headers=reader).json()["description"] == meaning
    bad = _health(description="tab\there")
    answer = central.put("/api/v1/series", json=[bad], headers=headers)
    assert answer.status_code == 422


def test_an_app_retires_the_series_it_no_longer_writes_and_only_its_own(central):
    headers = _service(central)
    old = "app-linkcraft:pv.status"
    central.put("/api/v1/series", json=[_health(), {**_health(), "signal": old}], headers=headers)
    other = central.post(
        "/api/v1/series/retire", json={"signals": [old, "app-modelcraft:x"]}, headers=headers
    )
    assert other.status_code == 403  # another app's source: nothing retired
    person = central.post(
        "/api/v1/series/retire", json={"signals": [old]}, headers=_as(central, "eng")
    )
    assert person.status_code == 403
    answer = central.post(
        "/api/v1/series/retire",
        json={"signals": [old, old, "app-linkcraft:never"]},
        headers=headers,
    )
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"retired": [old], "errors": []}
    reader = _as(central, "op")
    listed = central.get("/api/v1/signals", params={"app": "linkcraft"}, headers=reader).json()
    assert [item["id"] for item in listed] == [HEALTH]
    assert (
        central.get(f"/api/v1/signals/{old}/series", params=WINDOW, headers=reader).status_code
        == 404
    )
    assert (
        central.post("/api/v1/series/retire", json={"signals": []}, headers=headers).status_code
        == 422
    )


def test_the_sdk_retires_through_processcraft_and_the_fake_answers_the_same(central):
    key = _app_key(central)["key"]
    client = PlantCraftClient("http://testserver", app="linkcraft", key=key, http_client=central)
    other = FakePlantCraft().client(None, app="linkcraft", key="test-app-key")
    for each in (client, other):
        each.put_series([_health()])
        assert each.retire_series([HEALTH, HEALTH]) == {"retired": [HEALTH], "errors": []}
        assert each.signals(app="linkcraft") == []
