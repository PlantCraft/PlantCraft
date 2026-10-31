"""Images on an action: the chart of the verdict it was opened from (plantcraft.actions.attachments)."""
# ruff: noqa: F811 (the fixture "signed" of tests/test_collaboration.py, imported to share it)

from __future__ import annotations

import base64

from plantcraft.actions.attachments import MAX_PER_ACTION, sniff
from tests.test_collaboration import _person, signed  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _b64(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()


def test_only_real_images_are_kept():
    assert sniff(PNG) == "image/png"
    assert sniff(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None


def test_an_action_keeps_the_chart_it_was_opened_with(signed):
    action = signed.post(
        "/api/actions",
        json={"title": "FIC-101: Stiction", "description": "Health 42", "refs": ["asset:FIC-101"]},
    ).json()
    answer = signed.post(
        f"/api/actions/{action['action_id']}/files",
        json={"name": "FIC-101 chart.png", "data": _b64(PNG)},
    )
    assert answer.status_code == 201, answer.text
    (found,) = answer.json()["files"]
    assert found["content_type"] == "image/png" and found["size"] == len(PNG)
    image = signed.get(f"/api/actions/{action['action_id']}/files/{found['file_id']}")
    assert image.status_code == 200 and image.content == PNG
    assert image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"
    assert (
        signed.get(f"/api/actions/{action['action_id']}").json()["files"][0]["name"]
        == "FIC-101 chart.png"
    )
    # A declared PNG that is an SVG, and text that is not base64, are refused.
    svg = base64.b64encode(b"<svg onload='alert(1)'/>").decode()
    bad = signed.post(
        f"/api/actions/{action['action_id']}/files", json={"name": "x.png", "data": svg}
    )
    assert bad.status_code == 422
    assert (
        signed.post(
            f"/api/actions/{action['action_id']}/files", json={"data": "not base64!!"}
        ).status_code
        == 422
    )
    for _ in range(MAX_PER_ACTION - 1):
        signed.post(f"/api/actions/{action['action_id']}/files", json={"data": _b64(PNG)})
    assert (
        signed.post(
            f"/api/actions/{action['action_id']}/files", json={"data": _b64(PNG)}
        ).status_code
        == 422
    )
    assert signed.get(f"/api/actions/{action['action_id']}/files/999").status_code == 404


def test_who_does_not_see_the_action_does_not_see_its_images(signed):
    action = signed.post("/api/actions", json={"title": "Private", "owner": "admin"}).json()
    file_id = signed.post(
        f"/api/actions/{action['action_id']}/files", json={"data": _b64(PNG)}
    ).json()["files"][0]["file_id"]
    stranger = _person(signed, "rui")
    assert stranger.get(f"/api/actions/{action['action_id']}/files/{file_id}").status_code == 404
    assert (
        stranger.post(
            f"/api/actions/{action['action_id']}/files", json={"data": _b64(PNG)}
        ).status_code
        == 404
    )
