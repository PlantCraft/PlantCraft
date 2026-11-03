"""The picture of a block (Link and Models, round 9 M2): checked once, then kept with the version.

A block may carry one image, drawn in its node, in the palette and on its page. It travels as a
``data:`` URL. PNG, JPEG and WebP are taken as they are once their first bytes say what they are;
an SVG is rebuilt from a short list of drawing elements and attributes, so no script, event
handler, external reference or embedded document survives. Every image is at most
``MAX_IMAGE_BYTES``.

- ``block_image(value)``: the checked data URL (``""`` for none), or ``ImageError``.
- ``image_bytes(data_url)``: its type and bytes; ``image_tag(data_url)`` a short content tag for
  cache-busting URLs (``?v=``).
- ``image_response(data_url)``: the HTTP response of an image route, cached for good (its URL
  carries the tag) and served with a policy that runs nothing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import xml.etree.ElementTree as ET
from typing import Any

from plantcraft_sdk.i18n import t

MAX_IMAGE_BYTES = 256 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/svg+xml")

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

# What an SVG may keep: shapes, text, groups and paint servers. Anything else is dropped with
# everything inside it (script, foreignObject, image, a, animate, style, iframe…).
SVG_ELEMENTS = frozenset(
    {
        "svg",
        "g",
        "defs",
        "symbol",
        "use",
        "title",
        "desc",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "text",
        "tspan",
        "linearGradient",
        "radialGradient",
        "stop",
        "clipPath",
        "mask",
        "pattern",
        "marker",
    }
)
SVG_ATTRIBUTES = frozenset(
    {
        "id",
        "class",
        "viewBox",
        "preserveAspectRatio",
        "width",
        "height",
        "x",
        "y",
        "x1",
        "x2",
        "y1",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "fx",
        "fy",
        "d",
        "points",
        "pathLength",
        "transform",
        "fill",
        "fill-opacity",
        "fill-rule",
        "stroke",
        "stroke-width",
        "stroke-opacity",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-miterlimit",
        "opacity",
        "color",
        "visibility",
        "display",
        "clip-path",
        "clip-rule",
        "mask",
        "marker-start",
        "marker-mid",
        "marker-end",
        "markerWidth",
        "markerHeight",
        "refX",
        "refY",
        "orient",
        "offset",
        "stop-color",
        "stop-opacity",
        "gradientUnits",
        "gradientTransform",
        "spreadMethod",
        "patternUnits",
        "patternContentUnits",
        "patternTransform",
        "clipPathUnits",
        "maskUnits",
        "maskContentUnits",
        "font-family",
        "font-size",
        "font-weight",
        "font-style",
        "text-anchor",
        "dominant-baseline",
        "letter-spacing",
        "dx",
        "dy",
        "href",
        "style",
        "version",
    }
)
# A paint or reference may only point inside the picture (``url(#id)``, ``#id``).
_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
_DATA_URL = re.compile(r"^data:([a-z0-9.+/-]+);base64,([A-Za-z0-9+/=\s]*)$", re.I)


class ImageError(ValueError):
    """The image cannot be kept: what is wrong, in words for the person who chose it."""


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _local(value: str) -> bool:
    """Whether every reference in an attribute stays inside the picture."""

    return all(match.group(2).strip().startswith("#") for match in _URL.finditer(value))


def _style(value: str) -> str | None:
    lowered = value.lower()
    if any(word in lowered for word in ("expression", "javascript:", "@import", "behavior")):
        return None
    return value if _local(value) else None


def _name(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        namespace, _, local = tag[1:].partition("}")
        return namespace, local
    return "", tag


def _clean(element: ET.Element) -> ET.Element | None:
    namespace, local = _name(element.tag)
    if namespace not in ("", SVG_NS) or local not in SVG_ELEMENTS:
        return None
    kept = ET.Element(f"{{{SVG_NS}}}{local}")
    for key, value in element.attrib.items():
        attribute_namespace, attribute = _name(key)
        if attribute_namespace == XLINK_NS and attribute == "href":
            attribute_namespace = ""
        if attribute_namespace or attribute not in SVG_ATTRIBUTES:
            continue
        if attribute == "href":
            if not value.strip().startswith("#"):
                continue
        elif attribute == "style":
            cleaned = _style(value)
            if cleaned is None:
                continue
            value = cleaned
        elif not _local(value):
            continue
        kept.set(attribute, value)
    kept.text = element.text if local in ("text", "tspan", "title", "desc") else None
    for child in element:
        cleaned = _clean(child)
        if cleaned is not None:
            cleaned.tail = child.tail if local in ("text", "tspan") else None
            kept.append(cleaned)
    return kept


def clean_svg(data: bytes) -> bytes:
    """The SVG rebuilt from what it may keep (``ImageError`` when it is not an SVG)."""

    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise ImageError(t("An SVG with a DOCTYPE or entities is not taken: save it plainly."))
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ImageError(t("The SVG cannot be read: {error}.", error=exc)) from exc
    if _name(root.tag)[1] != "svg":
        raise ImageError(t("The file is not an SVG picture."))
    cleaned = _clean(root)
    if cleaned is None:
        raise ImageError(t("The file is not an SVG picture."))
    ET.register_namespace("", SVG_NS)
    return ET.tostring(cleaned, encoding="utf-8", xml_declaration=False)


def image_bytes(data_url: str) -> tuple[str, bytes]:
    """The type and bytes of a data URL (``ImageError`` when it is not one)."""

    match = _DATA_URL.match(data_url.strip())
    if not match:
        raise ImageError(t("The image is not a base64 data URL."))
    try:
        data = base64.b64decode(re.sub(r"\s+", "", match.group(2)), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageError(t("The image's base64 cannot be read.")) from exc
    return match.group(1).lower(), data


def _as_url(kind: str, data: bytes) -> str:
    return f"data:{kind};base64,{base64.b64encode(data).decode('ascii')}"


def block_image(value: str | None) -> str:
    """A block's image, checked: the data URL to keep (``""`` for none)."""

    if not value:
        return ""
    declared, data = image_bytes(value)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(
            t(
                "The image is {size} KB: a block's image is at most {limit} KB.",
                size=len(data) // 1024,
                limit=MAX_IMAGE_BYTES // 1024,
            )
        )
    found = _sniff(data)
    if found:
        return _as_url(found, data)
    if declared == "image/svg+xml" or data.lstrip()[:5].lower() in (b"<?xml", b"<svg "):
        cleaned = clean_svg(data)
        if len(cleaned) > MAX_IMAGE_BYTES:
            raise ImageError(t("The SVG is too large once cleaned."))
        return _as_url("image/svg+xml", cleaned)
    raise ImageError(t("A block's image is a PNG, JPEG, WebP or SVG file."))


def raw_image(data: bytes) -> str:
    """Bytes kept without their type (a Modelica ``Bitmap``'s ``imageSource``) as a checked data
    URL, ``""`` when they are not a picture this module takes."""

    kind = _sniff(data) or ("image/svg+xml" if b"<svg" in data[:4096] else None)
    if kind is None:
        return ""
    try:
        return block_image(_as_url(kind, data))
    except ImageError:
        return ""


def image_tag(data_url: str) -> str:
    """A short tag of the image's content, for URLs that change when it does."""

    return hashlib.sha256(data_url.encode("ascii", "replace")).hexdigest()[:12]


def image_response(data_url: str) -> Any:
    """The HTTP response of an image route (Starlette): its URL carries ``image_tag``, so it is
    cached for good; the policy runs nothing even if a browser opens the SVG on its own."""

    from starlette.responses import Response

    kind, data = image_bytes(data_url)
    if kind not in IMAGE_TYPES:
        raise ImageError(t("Not a block image."))
    return Response(
        data,
        media_type=kind,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = [
    "IMAGE_TYPES",
    "MAX_IMAGE_BYTES",
    "ImageError",
    "block_image",
    "clean_svg",
    "image_bytes",
    "image_response",
    "image_tag",
    "raw_image",
]
