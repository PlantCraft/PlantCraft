"""HTTP routes: the diagrams found in the documents, and the plant map built from them.

Everything is read as the person: only diagrams of documents they may read are listed and
joined into their map. Nothing is written to PlantCraft; the map is offered as an asset file the
person reviews on PlantCraft's Assets › Import.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import Response
from plantcraft_sdk.auth import User
from pydantic import BaseModel, ConfigDict, Field

from doccraft.api.deps import CurrentUser, EditorUser, RuntimeDep
from doccraft.api.runtime import Runtime
from doccraft.i18n import t
from doccraft.plantmap.build import LIST_COLUMNS, asset_file, build_map, lists
from doccraft.plantmap.dexpi import dexpi_xml

router = APIRouter(prefix="/api", tags=["plant map"])
IMAGE_DPI = 110


def _visible(rt: Runtime, user: User) -> set[str]:
    perms = rt.permissions(user)
    return {d["doc_id"] for d in perms.docs(rt.store.documents(perms.visible_folders()))}


def _known(rt: Runtime) -> set[str] | None:
    try:
        return set(rt.library.known_ids())
    except Exception:  # noqa: BLE001 - without PlantCraft the map says "unknown"
        return None


@router.get("/diagrams")
def list_diagrams(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    return rt.store.diagrams(_visible(rt, user))


def _diagram_or_404(rt: Runtime, user: User, rev_id: str, page: int) -> dict[str, Any]:
    found = rt.store.diagram(rev_id, page)
    if found is None or found["doc_id"] not in _visible(rt, user):
        raise HTTPException(status_code=404, detail=t("Diagram not found."))
    return found


@router.get("/diagrams/{rev_id}/{page}")
def get_diagram(
    rt: RuntimeDep,
    user: CurrentUser,
    rev_id: str = Path(max_length=40),
    page: int = Path(ge=1, le=100000),
) -> dict[str, Any]:
    found = _diagram_or_404(rt, user, rev_id, page)
    found.pop("sha256", None)
    return found


@router.get("/diagrams/{rev_id}/{page}/image")
def diagram_image(
    rt: RuntimeDep,
    user: CurrentUser,
    rev_id: str = Path(max_length=40),
    page: int = Path(ge=1, le=100000),
) -> Response:
    """The page as a PNG drawn here (PDF, image) so the browser never runs the file."""

    found = _diagram_or_404(rt, user, rev_id, page)
    path = rt.store.file_path(found["sha256"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail=t("File not found."))
    data = path.read_bytes()
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=3600",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    try:
        png = _render(data, found["format"], page)
    except Exception as error:  # noqa: BLE001 - an unreadable page shows no picture
        raise HTTPException(status_code=422, detail=t("This page cannot be drawn.")) from error
    if png is None:
        # An SVG is sent as an image: an <img> never runs its scripts.
        return Response(data, media_type="image/svg+xml", headers=headers)
    return Response(png, media_type="image/png", headers=headers)


def _render(data: bytes, fmt: str, page: int) -> bytes | None:
    if fmt == "pdf":
        import pypdfium2

        doc = pypdfium2.PdfDocument(data)
        try:
            image = doc[page - 1].render(scale=IMAGE_DPI / 72).to_pil()
        finally:
            doc.close()
    elif fmt == "drawing" and data.lstrip()[:5].lower() in {b"<?xml", b"<svg "}:
        return None
    else:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.thumbnail((4000, 4000))
    out = io.BytesIO()
    image.convert("L").save(out, format="PNG", optimize=True)
    return out.getvalue()


@router.get("/plant-map")
def plant_map(rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    diagrams = rt.store.diagrams(_visible(rt, user), full=True)
    return build_map(diagrams, _known(rt), rt.store.map_reviews())


@router.get("/plant-map/asset-file")
def plant_map_asset_file(rt: RuntimeDep, user: CurrentUser) -> Response:
    """The map as PlantCraft's asset file: Assets › Import reviews it before anything changes."""

    diagrams = rt.store.diagrams(_visible(rt, user), full=True)
    document = asset_file(build_map(diagrams, None, rt.store.map_reviews()))
    rt.audit(user, "plantmap.export", "plant-map", {"assets": len(document["assets"])})
    return Response(
        json.dumps(document, indent=1, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="plant-map-assets.json"'},
    )


@router.get("/plant-map/dexpi.xml")
def plant_map_dexpi(rt: RuntimeDep, user: CurrentUser) -> Response:
    """The map in DEXPI (Proteus XML) for a P&ID tool: equipment, lines and instrument loops."""

    diagrams = rt.store.diagrams(_visible(rt, user), full=True)
    document = dexpi_xml(build_map(diagrams, None, rt.store.map_reviews()))
    rt.audit(user, "plantmap.export", "plant-map", {"format": "dexpi", "bytes": len(document)})
    return Response(
        document,
        media_type="application/xml",
        headers={
            "Content-Disposition": 'attachment; filename="plant-map-dexpi.xml"',
            "X-Content-Type-Options": "nosniff",
        },
    )


class Review(BaseModel):
    """An item (``kind`` item, ``key`` its tag) or a relation (``kind`` relation, ``key``
    ``from|type|to``) approved, rejected, or back to unchecked (``verdict`` empty)."""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=200)
    kind: str = Field(pattern="^(item|relation)$")
    verdict: str = Field(pattern="^(approved|rejected|)$")


@router.put("/plant-map/reviews")
def review(body: Review, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    rt.store.set_map_review(body.key, body.kind, body.verdict, user.username)
    rt.audit(user, "plantmap.review", body.key, {"kind": body.kind, "verdict": body.verdict})
    return {"key": body.key, "verdict": body.verdict}


@router.get("/plant-map/lists/{kind}.csv")
def plant_map_list(
    rt: RuntimeDep,
    user: CurrentUser,
    kind: str = Path(pattern="^(equipment|instruments|lines|loops)$"),
) -> Response:
    """Equipment, instrument, process line or loop list of the map, for a spreadsheet."""

    assert kind in LIST_COLUMNS
    diagrams = rt.store.diagrams(_visible(rt, user), full=True)
    rows = lists(build_map(diagrams, _known(rt), rt.store.map_reviews()), kind)
    out = io.StringIO()
    writer = csv.writer(out)
    for row in rows:
        writer.writerow([_cell(value) for value in row])
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="plant-map-{kind}.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _cell(value: str) -> str:
    """A text read from a drawing never starts a spreadsheet formula."""

    text = str(value)
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text
