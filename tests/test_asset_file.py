# ruff: noqa: F811  (the fixtures admin, eng and viewer come from test_asset_model.py)
"""Assets › Export and Import: the tree alone, in five formats, reviewed before it is applied."""

from __future__ import annotations

import io
import json

import pytest

from tests.test_asset_model import _login, _rt, admin, app, eng, viewer  # noqa: F401

DOCUMENT = {
    "assets": [
        {
            "asset_id": "U-300",
            "name": "Treating unit",
            "type": "unit",
            "attributes": {"unit_code": "U-300"},
        },
        {"asset_id": "u-300-amine", "name": "Amine", "type": "area", "parent_id": "U-300"},
        {
            "asset_id": "C-301",
            "name": "Amine absorber",
            "type": "Column",  # a type's name works too
            "parent_id": "u-300-amine",
            "attributes": {"Trays or stages": 20, "diameter": 1.8, "colour": "blue"},
            "signals": [{"role": "Top pressure", "tag": "pv"}],
        },
        {
            "asset_id": "PT-301",
            "name": "Absorber pressure transmitter",
            "type": "instrument",
            "parent_id": "C-301",
            "signals": [{"role": "measurement", "tag": "pv"}],
        },
    ],
    "relations": [{"from": "PT-301", "type": "measures", "to": "C-301"}],
}


def test_read_review_and_apply_a_document(admin):
    content = json.dumps(DOCUMENT).encode()
    review = admin.post(
        "/api/asset-file/read", params={"filename": "assets.json"}, content=content
    ).json()
    assert review["counts"] == {"create": 4, "update": 0, "unchanged": 0, "error": 0}
    column = next(row for row in review["assets"] if row["asset_id"] == "C-301")
    assert column["type"] == "column"
    assert column["attributes"] == {"trays": 20, "diameter": 1.8}
    assert any("colour" in warning for warning in column["warnings"])
    assert column["signals"] == [{"role": "top_pressure", "tag": "pv", "source_id": "scenario"}]
    # The first asset has no parent: it goes under the plant.
    assert review["assets"][0]["parent_id"] == _rt(admin).platform.root_asset_id
    applied = admin.post("/api/asset-file/apply", json=review).json()
    assert applied["applied"] and applied["created"] == 4 and applied["related"] == 1
    store = _rt(admin).platform.workspace.assets
    assert store.get("C-301")["parent_id"] == "u-300-amine"
    assert store.attributes("C-301")["trays"] == 20
    # The flow PV is now referenced by the loop and by the column and the transmitter.
    users = {item["asset_id"] for item in store.signal_assets(["pv"])["pv"]}
    assert {"C-301", "PT-301", "FIC-101"} <= users
    # Each asset's page says where else its signals are used.
    detail = admin.get("/api/assets/PT-301").json()
    used = {item["asset_id"] for item in detail["signals"][0]["used_in"]}
    assert {"C-301", "FIC-101"} <= used and "PT-301" not in used
    again = admin.post(
        "/api/asset-file/read", params={"filename": "assets.json"}, content=content
    ).json()
    assert again["counts"]["unchanged"] == 4 and not again["can_apply"]


def test_review_edits_and_errors_block_the_apply(admin):
    document = json.loads(json.dumps(DOCUMENT))
    document["assets"][2]["type"] = "spaceship"
    review = admin.post("/api/asset-file/review", json=document).json()
    assert review["counts"]["error"] == 1 and not review["can_apply"]
    assert admin.post("/api/asset-file/apply", json=document).json()["applied"] is False
    assert _rt(admin).platform.workspace.assets.get("U-300") is None
    # Leaving the bad row out: its child goes under the anchor, the rest applies.
    document["assets"][2]["include"] = False
    area = next(
        item for item in _rt(admin).platform.workspace.assets.list() if item["kind"] == "area"
    )
    review = admin.post(
        "/api/asset-file/review", json={**document, "anchor": area["asset_id"]}
    ).json()
    child = next(row for row in review["assets"] if row["asset_id"] == "PT-301")
    assert child["parent_id"] == area["asset_id"] and review["can_apply"]


def test_only_admins_import_and_everyone_exports(admin, eng, viewer):
    assert eng.post("/api/asset-file/review", json=DOCUMENT).status_code == 403
    assert viewer.get("/api/asset-file/export.json").status_code == 200


@pytest.mark.parametrize("kind", ["json", "csv", "xlsx", "b2mml", "af"])
def test_every_export_reads_back_unchanged(admin, kind):
    admin.post("/api/asset-file/apply", json=DOCUMENT)
    response = admin.get(f"/api/asset-file/export.{kind}")
    assert response.status_code == 200, response.text
    name = {"json": "a.json", "csv": "a.csv", "xlsx": "a.xlsx", "b2mml": "a.xml", "af": "a.xml"}[
        kind
    ]
    review = admin.post(
        "/api/asset-file/read", params={"filename": name}, content=response.content
    ).json()
    assert review["counts"]["error"] == 0, [
        row["errors"] for row in review["assets"] if row["errors"]
    ]
    assert review["counts"]["create"] == 0
    ids = {row["asset_id"] for row in review["assets"]}
    assert {"U-300", "C-301", "PT-301", "FIC-101"} <= ids


def test_b2mml_levels_become_types(admin):
    xml = b"""<?xml version="1.0"?>
<EquipmentInformation xmlns="http://www.mesa.org/xml/B2MML">
  <Equipment><ID>Ent</ID><EquipmentLevel>Enterprise</EquipmentLevel>
    <Equipment><ID>North</ID><EquipmentLevel>Site</EquipmentLevel>
      <Equipment><ID>A-1</ID><Description>Utilities</Description><EquipmentLevel>Area</EquipmentLevel>
        <Equipment><ID>PC-1</ID><EquipmentLevel>ProcessCell</EquipmentLevel>
          <Equipment><ID>U-1</ID><EquipmentLevel>Unit</EquipmentLevel>
            <EquipmentProperty><ID>manufacturer</ID><Value><ValueString>ACME</ValueString></Value></EquipmentProperty>
          </Equipment>
        </Equipment>
      </Equipment>
    </Equipment>
  </Equipment>
</EquipmentInformation>"""
    review = admin.post(
        "/api/asset-file/read", params={"filename": "plant.xml"}, content=xml
    ).json()
    types = {row["asset_id"]: (row["type"], row["parent_id"]) for row in review["assets"]}
    root = _rt(admin).platform.root_asset_id
    assert types == {"A-1": ("unit", root), "PC-1": ("area", "A-1"), "U-1": ("equipment", "PC-1")}
    assert review["assets"][-1]["attributes"] == {"manufacturer": "ACME"}


def test_af_elements_templates_and_pi_points(admin):
    xml = rb"""<?xml version="1.0" encoding="utf-8"?>
<AF SchemaVersion="2.0"><AFDatabase><Name>Plant</Name>
  <AFElement><Name>P-101</Name><Description>Feed pump</Description><Template>Pump</Template>
    <AFAttribute><Name>Rated flow</Name><Value type="Double">120</Value></AFAttribute>
    <AFAttribute><Name>Flow</Name><DataReference>PI Point</DataReference><ConfigString>\\PISRV\pv;ReadOnly=False</ConfigString></AFAttribute>
    <AFAttribute><Name>Status</Name><DataReference>PI Point</DataReference><ConfigString>\\%Server%\%Element%.%Attribute%</ConfigString></AFAttribute>
    <AFElement><Name>FT-101</Name><Template>Instrument</Template></AFElement>
  </AFElement>
</AFDatabase></AF>"""
    review = admin.post("/api/asset-file/read", params={"filename": "af.xml"}, content=xml).json()
    pump = review["assets"][0]
    assert (pump["asset_id"], pump["name"], pump["type"]) == ("P-101", "Feed pump", "pump")
    assert pump["attributes"] == {"rated_flow": 120}
    assert [signal["tag"] for signal in pump["signals"]] == ["pv"]
    assert any("PISRV" in warning for warning in pump["warnings"])
    assert review["assets"][1]["parent_id"] == "P-101"
    assert any("substitutions" in note for note in review["notes"])


def test_files_that_cannot_be_read(admin):
    def read(name: str, content: bytes) -> int:
        return admin.post(
            "/api/asset-file/read", params={"filename": name}, content=content
        ).status_code

    assert read("a.txt", b"x") == 422
    assert read("a.json", b"{") == 422
    assert read("a.json", json.dumps({"sources": [], "assets": []}).encode()) == 422
    assert read("a.xml", b'<!DOCTYPE x [<!ENTITY a "b">]><x/>') == 422
    assert read("a.xml", b"<nothing/>") == 422
    assert read("a.csv", b"name\nx\n") == 422
    assert read("a.xlsx", io.BytesIO(b"not a workbook").getvalue()) == 422


def test_the_demo_seed_names_the_plant(admin):
    from plantcraft import demo_seed

    class Client(demo_seed.Http):
        """The seed's client, through the test client instead of the network."""

        def call(self, method, path, body=None, *, ok=(), raw=None, content_type=""):
            response = (
                admin.request(method, path, json=body)
                if raw is None
                else admin.request(method, path, content=raw)
            )
            if response.status_code >= 400 and response.status_code not in ok:
                raise demo_seed.SeedError(f"{method} {path}: {response.status_code}")
            return response.status_code, response.json() if response.content else None

    store = _rt(admin).platform.workspace.assets
    demo_seed.name_the_plant(Client("http://test"))
    root = store.get(_rt(admin).platform.root_asset_id)
    assert root["name"] == demo_seed.PLANT["name"] and root["origin"] == "manual"
    assert store.attributes(root["asset_id"])["location"] == demo_seed.PLANT_RECORD["location"]


def test_the_asset_tree_prompt_asks_for_the_files_own_json(admin):
    """Copy as prompt on Assets › Import: fields, an example the import reads, the types."""

    answer = admin.get("/api/prompts/asset-tree").json()
    text = answer["text"]
    assert answer["title"] == "Asset tree import" and answer["omitted"] == []
    assert [part["label"] for part in answer["parts"]] == [
        "Fields of each asset",
        "Example file",
        "Asset types of this installation",
    ]
    assert '"format": "processcraft-assets"' in text and "Build the asset tree" in text
    assert '"type": "equipment"' in text and '"signal_roles"' in text
    # The example is a file the import reads without an error.
    example = json.loads(answer["parts"][1]["content"])
    review = admin.post("/api/asset-file/review", json=example).json()
    assert review["counts"]["error"] == 0 and review["counts"]["create"] == 2
    convert = admin.get("/api/prompts/asset-tree", params={"question": "convert"}).json()
    assert "Convert the export of another system" in convert["text"]


def test_the_last_import_can_be_undone_once(admin, eng):
    """An import into a plant already set up can be taken back."""

    store = _rt(admin).platform.workspace.assets
    assert admin.get("/api/asset-file/last-import").json() == {"import": None}
    assert admin.post("/api/asset-file/undo").status_code == 409
    first = admin.post(
        "/api/asset-file/read", params={"filename": "a.json"}, content=json.dumps(DOCUMENT).encode()
    ).json()
    assert admin.post("/api/asset-file/apply", json=first).json()["applied"]
    store.set_attributes("C-301", {"diameter": 2.0}, actor="admin")
    # A second file renames the absorber, changes its diameter and adds an asset under it.
    second = {
        "assets": [
            {
                "asset_id": "C-301",
                "name": "Absorber (renamed)",
                "type": "column",
                "parent_id": "u-300-amine",
                "attributes": {"diameter": 3.5},
            },
            {"asset_id": "LT-302", "name": "Level", "type": "instrument", "parent_id": "C-301"},
        ]
    }
    review = admin.post(
        "/api/asset-file/read", params={"filename": "b.json"}, content=json.dumps(second).encode()
    ).json()
    assert admin.post("/api/asset-file/apply", json=review).json()["applied"]
    assert store.get("C-301")["name"] == "Absorber (renamed)" and store.get("LT-302")
    last = admin.get("/api/asset-file/last-import").json()["import"]
    assert last["can_undo"] and last["summary"] == {"created": 1, "updated": 1, "relations": 0}
    assert eng.post("/api/asset-file/undo").status_code == 403

    done = admin.post("/api/asset-file/undo").json()
    assert done["removed"] == 1 and done["restored"] == 1
    assert store.get("LT-302") is None
    assert store.get("C-301")["name"] == "Amine absorber"
    assert store.attributes("C-301")["diameter"] == 2.0  # as before the import, the hand edit kept
    assert store.get("PT-301") is not None  # the first import stays
    assert done["import"]["can_undo"] is False
    assert admin.post("/api/asset-file/undo").status_code == 409
    rows = admin.get("/api/audit", params={"action": "assets"}).json()["rows"]
    assert rows[0]["action"] == "assets.import_undone"
