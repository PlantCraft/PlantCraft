"""Export: tags, loops, groups of loops or a whole unit as a data package (``/api/export``)."""

from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest

from tests.conftest import client_for
from tests.test_api import loaded  # noqa: F401
from tests.test_query import T0

PERIOD = {"start": T0.isoformat(), "end": (T0.replace(hour=T0.hour + 1)).isoformat()}
ASSETS = [
    {"id": "site", "name": "Site", "kind": "site", "parent_id": None},
    {"id": "u100", "name": "Unit 100", "kind": "unit", "parent_id": "site"},
    {"id": "area-1", "name": "Area 1", "kind": "area", "parent_id": "u100"},
    {
        "id": "tic-100",
        "name": "TIC-100",
        "kind": "loop",
        "parent_id": "area-1",
        "attributes": {"description": "Reactor temperature", "loop_type": "temperature"},
        "signals": {"pv": "plant:TI-100.PV", "mode": "plant:FIC-101.MODE", "sp": "plant:TI-100.SP"},
    },
    {
        "id": "tt-1",
        "name": "TT 1",
        "kind": "equipment",
        "parent_id": "area-1",
        "signals": {"pv": "plant:Area/1/TT"},
    },
    {"id": "u200", "name": "Unit 200", "kind": "unit", "parent_id": "site"},
]


@pytest.fixture
def plant(fake, loaded):  # noqa: F811
    fake.assets = [
        {"signals": {}, "attributes": {}, "relations": [], "type_path": [item["kind"]], **item}
        for item in ASSETS
    ]
    return loaded


def _zip(answer) -> tuple[zipfile.ZipFile, dict]:
    assert answer.status_code == 200, answer.text
    archive = zipfile.ZipFile(io.BytesIO(answer.content))
    return archive, json.loads(archive.read("manifest.json"))


def _rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(archive.read(name).decode())))


def test_options_list_the_tree_with_what_each_branch_exports(client, plant):
    body = client.get("/hist/api/export/options").json()
    rows = {row["id"]: row for row in body["assets"]}
    assert [row["id"] for row in body["assets"]][:3] == ["site", "u100", "area-1"]
    assert rows["u100"]["loops"] == 1 and rows["u100"]["signals"] == 3
    assert rows["u100"]["missing"] == 1  # TI-100.SP is not archived here
    assert rows["tic-100"]["loop"] is True and rows["tic-100"]["depth"] == 3
    assert rows["u200"]["signals"] == 0
    assert body["points"] == 3 and body["max_signals"] == 500


def test_a_whole_unit_exports_its_tags_assets_and_plant_map(client, plant, fake):
    choice = {"assets": ["u100"], **PERIOD, "step_seconds": 600}
    preview = client.post("/hist/api/export/preview", json=choice).json()
    assert preview == {
        "signals": 3, "assets": 4, "loops": 1, "missing": 1,
        "tags": ["Area/1/TT", "FIC-101.MODE", "TI-100.PV"],
    }  # fmt: skip
    answer = client.post("/hist/api/export", json=choice)
    # The page says what the package holds after the download.
    assert (answer.headers["X-Package-Signals"], answer.headers["X-Package-Rows"]) == ("3", "6")
    assert answer.headers["X-Package-Not-Read"] == "1"
    archive, manifest = _zip(answer)
    assert sorted(archive.namelist()) == sorted(
        ["manifest.json", "series.csv", "signals.csv", "assets.csv", "plant-map.json", "README.txt"]
    )
    assert manifest["counts"]["signals"] == 3 and manifest["counts"]["loops"] == 1
    assert manifest["not_read"] == {"plant:TI-100.SP": "Not archived by the Historian."}
    series = _rows(archive, "series.csv")
    assert list(series[0]) == ["time", "Area/1/TT", "FIC-101.MODE", "TI-100.PV"]
    assert len(series) == 6  # one hour in means of 10 minutes
    signals = {row["tag"]: row for row in _rows(archive, "signals.csv")}
    assert signals["TI-100.PV"]["unit"] == "degC" and signals["TI-100.PV"]["role"] == "pv"
    assert signals["TI-100.PV"]["asset"] == "tic-100"
    assets = {row["asset_id"]: row for row in _rows(archive, "assets.csv")}
    assert assets["tic-100"]["pv"] == "TI-100.PV" and assets["tic-100"]["parent_id"] == "area-1"
    plant_map = json.loads(archive.read("plant-map.json"))
    assert plant_map["format"] == "processcraft-map"
    assert [loop["loop_id"] for loop in plant_map["loops"]] == ["tic-100"]
    for item in manifest["files"]:
        assert len(archive.read(item["path"])) == item["bytes"]
    assert any(entry["action"] == "histcraft.export" for entry in fake.audit_log)


def test_tags_loops_and_groups_combine_without_repeats(client, plant):
    choice = {"signals": ["plant:TI-100.PV"], "assets": ["tic-100"], **PERIOD}
    preview = client.post("/hist/api/export/preview", json=choice).json()
    assert preview["signals"] == 2 and preview["assets"] == 1
    archive, manifest = _zip(client.post("/hist/api/export", json=choice))
    assert manifest["aggregation"] == {"raw": True}
    series = _rows(archive, "series.csv")
    # TI-100.PV's samples; the MODE change at 30 min falls on one of them.
    assert len(series) == 361 and series[180]["FIC-101.MODE"] == "MAN"


def test_an_anonymized_package_keeps_no_tag_and_its_key_stays_apart(client, plant):
    choice = {"assets": ["area-1"], **PERIOD, "step_seconds": 600, "anonymize": True}
    archive, manifest = _zip(client.post("/hist/api/export", json=choice))
    text = b"".join(archive.read(name) for name in archive.namelist())
    for secret in (b"TI-100", b"TIC-100", b"FIC-101", b"Reactor", b"Area/1/TT", b"area-1"):
        assert secret not in text
    assert manifest["anonymized"] is True and manifest["not_read"] == {}
    key = list(csv.DictReader(io.StringIO(client.post("/hist/api/export/key", json=choice).text)))
    assert {"kind": "signal", "alias": "S003", "id": "plant:TI-100.PV"} in key
    assert {"kind": "asset", "alias": "A002", "id": "tic-100"} in key


def test_choices_that_cannot_be_exported_say_why(client, plant):
    def status(**body):
        return client.post("/hist/api/export", json={**PERIOD, **body}).status_code

    assert status() == 422
    assert status(assets=["u200"]) == 422  # nothing archived under it
    assert status(assets=["nope"]) == 422
    assert status(signals=["plant:NOPE"]) == 422
    assert status(signals=["plant:TI-100.PV"], start=PERIOD["end"], end=PERIOD["start"]) == 422
    long = {"start": "2026-01-01T00:00:00Z", "end": "2026-01-20T00:00:00Z"}
    assert status(signals=["plant:TI-100.PV"], **long) == 422  # as recorded: 7 days at most
    assert status(signals=["plant:TI-100.PV"], step_seconds=3600, **long) == 200


def test_viewers_export_and_apps_do_not(runtime, fake, plant):
    with client_for(runtime, fake, "operator") as viewer:
        answer = viewer.post("/hist/api/export/preview", json={"signals": ["plant:TI-100.PV"]})
        assert answer.status_code == 200
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get("/hist/api/export/options").status_code == 401


def test_assets_of_any_kind_resolve_to_tags_for_the_list(client, plant):
    tags = client.post("/hist/api/export/resolve", json={"assets": ["u100"]}).json()["tags"]
    by_tag = {item["tag"]: item for item in tags}
    assert set(by_tag) == {"TI-100.PV", "FIC-101.MODE", "TI-100.SP", "Area/1/TT"}
    assert by_tag["TI-100.PV"] == {
        "signal": "plant:TI-100.PV", "tag": "TI-100.PV", "name": by_tag["TI-100.PV"]["name"],
        "unit": "degC", "archived": True, "asset_id": "tic-100", "asset_name": "TIC-100", "role": "pv",
    }  # fmt: skip
    assert by_tag["TI-100.SP"]["archived"] is False


def test_the_list_exports_only_its_tags_and_names_where_they_come_from(client, plant):
    # The person removed FIC-101.MODE from the list: it does not come back with the loop.
    choice = {
        "signals": ["plant:TI-100.PV", "plant:Area/1/TT"],
        "assets": ["u100"],
        "expand_assets": False,
        **PERIOD,
        "step_seconds": 600,
    }
    preview = client.post("/hist/api/export/preview", json=choice).json()
    assert preview["signals"] == 2
    archive, manifest = _zip(client.post("/hist/api/export", json=choice))
    assert list(_rows(archive, "series.csv")[0]) == ["time", "Area/1/TT", "TI-100.PV"]
    assets = {row["asset_id"] for row in _rows(archive, "assets.csv")}
    assert assets == {"u100", "tic-100", "tt-1"}


def test_a_saved_export_runs_again_and_only_its_author_or_an_editor_changes_it(
    runtime, fake, plant
):
    body = {
        "name": "Unit 100, last day",
        "signals": ["plant:TI-100.PV"],
        "assets": ["u100"],
        "hours": 24,
        "step_seconds": 600,
    }
    with client_for(runtime, fake, "operator") as viewer:
        saved = viewer.post("/hist/api/export/saved", json=body).json()
        assert saved["name"] == "Unit 100, last day" and saved["created_by"] == "operator"
        assert saved["hours"] == 24 and saved["signals"] == ["plant:TI-100.PV"]
        assert [item["id"] for item in viewer.get("/hist/api/export/saved").json()] == [saved["id"]]
        fixed = {**body, "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"}
        changed = viewer.put(f"/hist/api/export/saved/{saved['id']}", json=fixed).json()
        assert changed["hours"] is None and changed["start"] == fixed["start"]
        half = {**body, "start": "2026-01-01T00:00:00Z"}
        assert viewer.put(f"/hist/api/export/saved/{saved['id']}", json=half).status_code == 422
    with client_for(runtime, fake, "outsider") as other:
        assert other.delete(f"/hist/api/export/saved/{saved['id']}").status_code in {401, 403}
    with client_for(runtime, fake, "engineer") as editor:
        assert editor.delete(f"/hist/api/export/saved/{saved['id']}").json() == {
            "deleted": saved["id"]
        }
        assert editor.get("/hist/api/export/saved").json() == []


def test_a_public_demo_visit_exports_but_saves_no_choice(runtime, fake, plant):
    # Every visitor is the one demo account: a saved choice would be every visitor's to change.
    body = {"name": "Mine", "signals": ["plant:TI-100.PV"], "hours": 24, "step_seconds": 600}
    with client_for(runtime, fake, "operator") as viewer:
        kept = viewer.post("/hist/api/export/saved", json=body).json()
    visit = {"visit": "v1", "ends": 4102444800, "queries": 4, "queries_total": 8}
    with client_for(runtime, fake, None) as visitor:
        visitor.headers["Authorization"] = f"Bearer {fake.token('operator', demo=visit)}"
        refused = visitor.post("/hist/api/export/saved", json=body)
        assert refused.status_code == 403 and "nothing is saved" in refused.json()["detail"]
        assert visitor.put(f"/hist/api/export/saved/{kept['id']}", json=body).status_code == 403
        assert visitor.delete(f"/hist/api/export/saved/{kept['id']}").status_code == 403
        assert visitor.get("/hist/api/export/saved").status_code == 200


def test_each_step_keeps_the_aggregate_chosen(client, plant):
    """First, last, lowest, highest or mean per step."""

    base = {"signals": ["plant:TI-100.PV"], **PERIOD, "step_seconds": 600}
    raw, _ = _zip(client.post("/hist/api/export", json={"signals": ["plant:TI-100.PV"], **PERIOD}))
    values = [(row["time"], float(row["TI-100.PV"])) for row in _rows(raw, "series.csv")]
    first_step = [value for stamp, value in values if stamp < values[0][0][:14] + "10:00.000Z"]
    found = {}
    for aggregate in ("first", "last", "min", "max", "mean"):
        archive, manifest = _zip(
            client.post("/hist/api/export", json={**base, "aggregate": aggregate})
        )
        assert manifest["aggregation"] == {"step_seconds": 600, "aggregate": aggregate}
        rows = _rows(archive, "series.csv")
        assert len(rows) == 6 and rows[0]["time"].endswith(":00:00.000Z")
        found[aggregate] = float(rows[0]["TI-100.PV"])
    assert found["first"] == first_step[0] and found["last"] == first_step[-1]
    assert found["min"] == min(first_step) and found["max"] == max(first_step)
    assert found["min"] <= found["mean"] <= found["max"]
    assert client.post("/hist/api/export", json={**base, "aggregate": "median"}).status_code == 422
