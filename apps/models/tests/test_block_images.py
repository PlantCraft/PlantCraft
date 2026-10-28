"""A block's picture (round 9 M2): kept in the class's Icon annotation, so it is saved with the
file as a version; the catalog carries the path of the picture, not the picture."""

from __future__ import annotations

import base64

from modelcraft.modelica.edit import set_image
from modelcraft.modelica.interface import library_blocks
from tests.test_folders import GAIN

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()
ON_OFF = (
    'within Lib;\nblock OnOff "On/off"\n'
    "  Modelica.Blocks.Interfaces.RealInput u;\n  Modelica.Blocks.Interfaces.RealOutput y;\n"
    "protected\n  Boolean on(start = false, fixed = true);\nequation\n"
    "  when u > 1 then\n    on = true;\n  elsewhen u < 0 then\n    on = false;\n  end when;\n"
    "  y = if on then 1 else 0;\n"
    "  annotation(\n    Icon(graphics = {Rectangle(extent = {{-100, 100}, {100, -100}})}),\n"
    '    Documentation(info = "<html><p>Switches.</p></html>"));\nend OnOff;\n'
)


def test_the_picture_goes_in_the_icon_and_comes_out_leaving_the_rest():
    pictured = set_image(GAIN, "Utilities.Gain", PNG_URL)
    assert (
        'annotation(Icon(graphics={Bitmap(extent={{-100,-100},{100,100}}, imageSource="' in pictured
    )
    [spec] = library_blocks({"Utilities/Gain.mo": pictured}, library="l", library_name="L")
    assert spec["image"] == PNG_URL
    # Taking it out gives the file back as it was.
    assert set_image(pictured, "Utilities.Gain", "") == GAIN
    # A class with its own icon keeps its graphics and documentation ("end when" is not its end).
    drawn = set_image(ON_OFF, "Lib.OnOff", PNG_URL)
    assert "Rectangle(extent" in drawn and "Bitmap(" in drawn and drawn.count("annotation(") == 1
    [spec] = library_blocks({"Lib/OnOff.mo": drawn}, library="l", library_name="L")
    assert spec["image"] == PNG_URL and spec["description"] == "Switches."
    again = set_image(drawn, "Lib.OnOff", PNG_URL.replace("AAAA", "AAAB"))
    assert again.count("Bitmap(") == 1
    assert set_image(drawn, "Lib.OnOff", "") == ON_OFF


def test_a_block_picture_is_set_versioned_served_and_refused_when_not_a_picture(client):
    library = client.post("/api/blocks", json={"name": "Utilities"}).json()
    client.post(
        f"/api/projects/{library['id']}/files", json={"path": "Utilities/Gain.mo", "content": GAIN}
    )
    assert client.get("/api/catalog/Utilities.Gain").json()["image"] is None
    bad = client.put(
        "/api/catalog/Utilities.Gain/image", json={"image": "data:image/gif;base64,R0lGODlh"}
    )
    assert bad.status_code == 422 and "PNG, JPEG, WebP or SVG" in bad.text

    block = client.put("/api/catalog/Utilities.Gain/image", json={"image": PNG_URL}).json()
    assert block["image"].startswith("/api/catalog/Utilities.Gain/image?v=")
    assert "imageSource" in block["code"]
    listed = next(
        item
        for item in client.get("/api/catalog").json()["blocks"]
        if item["block_id"] == "Utilities.Gain"
    )
    assert listed["image"] == block["image"] and "base64" not in listed["image"]
    served = client.get(block["image"])
    assert served.status_code == 200 and served.content == PNG
    assert "immutable" in served.headers["cache-control"]

    # Taking it out is a new version; the version before still has its picture.
    removed = client.put("/api/catalog/Utilities.Gain/image", json={"image": ""}).json()
    assert removed["image"] is None and "imageSource" not in removed["code"]
    revisions = client.get(
        f"/api/projects/{library['id']}/files/Utilities/Gain.mo/revisions"
    ).json()
    old = client.get(f"/api/catalog/Utilities.Gain/versions/{revisions[0]['id']}").json()
    assert old["image"].startswith(
        f"/api/catalog/Utilities.Gain/versions/{revisions[0]['id']}/image?v="
    )
    assert client.get(old["image"]).content == PNG
    assert client.get("/api/catalog/Utilities.Gain/image").status_code == 404


def test_a_shipped_block_keeps_its_picture(client):
    shipped = next(item for item in client.get("/api/catalog").json()["blocks"])
    refused = client.put(f"/api/catalog/{shipped['block_id']}/image", json={"image": PNG_URL})
    assert refused.status_code in (403, 409, 422), refused.text
