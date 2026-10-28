"""Block images (round 9 M2): raster kept as is, SVG rebuilt without anything that runs."""

import base64

import pytest

from plantcraft_sdk.images import (
    MAX_IMAGE_BYTES,
    ImageError,
    block_image,
    image_bytes,
    image_response,
    image_tag,
    raw_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def url(kind: str, data: bytes) -> str:
    return f"data:{kind};base64,{base64.b64encode(data).decode()}"


def test_raster_images_are_kept_by_what_their_bytes_say():
    assert block_image(url("image/png", PNG)) == url("image/png", PNG)
    # The declared type does not decide: the first bytes do.
    assert block_image(url("image/jpeg", PNG)).startswith("data:image/png;")
    webp = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8
    assert block_image(url("image/webp", webp)).startswith("data:image/webp;")
    assert block_image("") == ""
    assert block_image(None) == ""


def test_what_is_not_a_picture_or_too_large_is_refused():
    with pytest.raises(ImageError, match="PNG, JPEG, WebP or SVG"):
        block_image(url("image/png", b"GIF89a" + b"\x00" * 10))
    with pytest.raises(ImageError, match="at most 256 KB"):
        block_image(url("image/png", PNG + b"\x00" * MAX_IMAGE_BYTES))
    with pytest.raises(ImageError, match="data URL"):
        block_image("https://example.com/a.png")
    with pytest.raises(ImageError, match="base64"):
        block_image("data:image/png;base64,@@@")


def test_an_svg_keeps_its_drawing_and_loses_everything_that_runs():
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
      viewBox="0 0 10 10" onload="alert(1)">
      <script>alert(2)</script>
      <defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs>
      <rect width="10" height="10" fill="url(#g)" onclick="alert(3)"/>
      <circle r="2" fill="url(https://evil.example/x)" style="fill: red"/>
      <use xlink:href="#g"/><use href="https://evil.example/a.svg#x"/>
      <foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>
      <a href="javascript:alert(4)"><text>link</text></a>
      <image href="https://evil.example/p.png"/>
      <text x="1" y="5">Tank</text>
    </svg>"""
    kind, data = image_bytes(block_image(url("image/svg+xml", svg)))
    assert kind == "image/svg+xml"
    text = data.decode()
    for gone in (
        "script",
        "alert",
        "onload",
        "onclick",
        "evil.example",
        "foreignObject",
        "<a",
        "image",
    ):
        assert gone not in text
    for kept in ("viewBox", "url(#g)", 'href="#g"', "Tank", "linearGradient", "fill: red"):
        assert kept in text


def test_an_svg_with_entities_or_that_is_not_svg_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>'
    with pytest.raises(ImageError, match="DOCTYPE"):
        block_image(url("image/svg+xml", bomb))
    with pytest.raises(ImageError, match="not an SVG"):
        block_image(url("image/svg+xml", b"<html><body/></html>"))
    with pytest.raises(ImageError, match="cannot be read"):
        block_image(url("image/svg+xml", b"<svg <"))


def test_raw_bytes_tags_and_the_response():
    assert raw_image(PNG).startswith("data:image/png;")
    assert raw_image(b"not a picture") == ""
    first = image_tag(url("image/png", PNG))
    assert len(first) == 12 and first != image_tag(url("image/png", PNG + b"\x01"))
    response = image_response(url("image/png", PNG))
    assert response.media_type == "image/png"
    assert response.body == PNG
    assert "immutable" in response.headers["cache-control"]
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_block_description_carries_the_path_of_its_image_not_the_image():
    from dataclasses import replace

    from plantcraft_sdk.blocks import BlockDocs, BlockSpec, describe_block, outport

    spec = BlockSpec(
        "custom.tank",
        "1",
        "custom",
        "Tank",
        BlockDocs(summary="s", description="d", reading="r"),
        outputs=(outport("level", "series", "Level", "The level"),),
    )
    assert describe_block(spec)["image"] is None
    pictured = replace(spec, image=url("image/png", PNG))
    path = describe_block(pictured)["image"]
    assert path == f"/api/blocks/custom.tank/image?v={image_tag(pictured.image)}"
    assert describe_block(pictured, image_route="/api/catalog/{block_id}/image")[
        "image"
    ].startswith("/api/catalog/custom.tank/image?v=")
