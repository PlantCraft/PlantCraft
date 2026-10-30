"""A block's page as Analytics': its documentation in parts (what it does,
how to read it, its formula), its defaults changed as a new version with what changed, and a
copy of any block, the shipped ones too, in the site's own library."""

from __future__ import annotations

from modelcraft.modelica.edit import set_binding
from modelcraft.modelica.interface import doc_sections, library_blocks
from tests.test_folders import GAIN


def test_the_documentation_comes_in_parts():
    annotation = (
        'Documentation(info = "<html><p>A lag.</p><h4>How to read it</h4><p>63 % in T.</p>'
        '<h4>Formula</h4><pre>T dy/dt = k u - y<br/>y(0) = k u</pre></html>")'
    )
    assert doc_sections(annotation) == {
        "description": "A lag.",
        "reading": "63 % in T.",
        "formula": "T dy/dt = k u - y\ny(0) = k u",
    }
    # Documentation without headings is all what it does.
    assert doc_sections('Documentation(info = "<html><p>y = k u.</p></html>")')["reading"] == ""


def test_every_shipped_block_says_what_it_does_and_how_to_read_it(client):
    blocks = client.get("/api/catalog").json()["blocks"]
    assert len(blocks) >= 28
    for block in blocks:
        assert block["description"] and block["reading"], block["block_id"]
        if not block["block_id"].startswith("PlantCraftSinks."):
            assert block["formula"], block["block_id"]


def test_a_binding_is_set_and_the_rest_of_the_declaration_stays():
    text = set_binding(GAIN, "Utilities.Gain", "k", "2.5")
    [spec] = library_blocks({"Utilities/Gain.mo": text}, library="l", library_name="L")
    assert next(item for item in spec["parameters"] if item["name"] == "k")["default"] == 2.5
    # The modifiers, the comment and the rest of the file stay as they were.
    assert text == GAIN.replace("k = 2;", "k = 2.5;")


def test_a_site_blocks_defaults_are_a_new_version_and_a_shipped_one_is_duplicated(client):
    library = client.post("/api/blocks", json={"name": "Utilities"}).json()
    client.post(
        f"/api/projects/{library['id']}/files", json={"path": "Utilities/Gain.mo", "content": GAIN}
    )
    # What changed is asked.
    missing = client.put("/api/catalog/Utilities.Gain/defaults", json={"values": {"k": 2}})
    assert missing.status_code == 422
    block = client.put(
        "/api/catalog/Utilities.Gain/defaults",
        json={"values": {"k": 3}, "version_note": "A larger gain"},
    ).json()
    assert next(item for item in block["parameters"] if item["name"] == "k")["default"] == 3
    assert block["version_note"] == "A larger gain"
    revisions = client.get(f"/api/projects/{library['id']}/files/Utilities/Gain.mo/revisions")
    assert revisions.status_code == 200 and len(revisions.json()) == 1
    unknown = client.put(
        "/api/catalog/Utilities.Gain/defaults", json={"values": {"nope": 1}, "version_note": "x"}
    )
    assert unknown.status_code == 422
    # A shipped block keeps its defaults, but any block can be duplicated into the site's library.
    shipped = client.put(
        "/api/catalog/PlantCraftEquipment.Tank/defaults",
        json={"values": {"A": 3}, "version_note": "x"},
    )
    assert shipped.status_code in (403, 409, 422)
    copy = client.post(
        "/api/catalog/PlantCraftEquipment.Tank/duplicate", json={"name": "Feed tank"}
    ).json()
    assert copy["block_id"].startswith("Utilities.") and copy["library"] == library["id"]
    assert copy["name"] == "Feed tank" and not copy["example"]
    assert [p["name"] for p in copy["parameters"]] == ["A", "Cv", "h_start"]
    again = client.post(
        "/api/catalog/PlantCraftEquipment.Tank/duplicate", json={"name": "Feed tank"}
    ).json()
    assert again["block_id"] != copy["block_id"]


def test_a_site_without_a_library_of_its_own_gets_one_with_the_first_copy(client):
    copy = client.post("/api/catalog/PlantCraftMath.Gain/duplicate", json={"name": "Scale"}).json()
    assert copy["block_id"] == "SiteBlocks.Scale"
    assert copy["library_name"] == "This site's blocks" and copy["summary"]
    assert "within SiteBlocks;" in copy["code"] and "end Scale;" in copy["code"]
