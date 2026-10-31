"""HTTP routes: the diagrams found in the documents, and the plant map built from them.

Everything is read as the person: only diagrams of documents they may read are listed and
joined into their map. Nothing is written to PlantCraft; the map is offered as an asset file the
person reviews on PlantCraft's Assets › Import.
"""

from __future__ import annotations

import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import Response
from plantcraft_sdk.auth import User

from doccraft.api.deps import CurrentUser, RuntimeDep
from doccraft.api.runtime import Runtime
from doccraft.i18n import t
from doccraft.plantmap.build import asset_file, build_map

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
    return build_map(diagrams, _known(rt))


@router.get("/plant-map/asset-file")
def plant_map_asset_file(rt: RuntimeDep, user: CurrentUser) -> Response:
    """The map as PlantCraft's asset file: Assets › Import reviews it before anything changes."""

    diagrams = rt.store.diagrams(_visible(rt, user), full=True)
    document = asset_file(build_map(diagrams, None))
    rt.audit(user, "plantmap.export", "plant-map", {"assets": len(document["assets"])})
    return Response(
        json.dumps(document, indent=1, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="plant-map-assets.json"'},
    )
