"""HTTP routes: the drawings (P&IDs) editors send, and the licence the app runs under."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Request

from pidcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, drawing_or_404
from pidcraft.drawings.models import DrawingChange, DrawingFields
from pidcraft.drawings.service import MAX_BYTES, Refused
from pidcraft.i18n import t

router = APIRouter(prefix="/api")
DrawingId = Path(pattern=r"^[a-f0-9]{12}$")


@router.get("/license")
def licence(rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    """The licence the app runs under now (the pages show it when it is missing or ending)."""

    return rt.licence.state.to_json()


@router.get("/drawings")
def list_drawings(rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    return rt.drawings.list()


@router.post("/drawings", status_code=201)
async def send_drawing(
    request: Request,
    rt: RuntimeDep,
    user: EditorUser,
    filename: str = Query(min_length=1, max_length=200),
    number: str = Query("", max_length=60),
    title: str = Query("", max_length=200),
    unit: str = Query("", max_length=60),
) -> dict[str, Any]:
    """The file as the request body; a drawing with the same number gets a new file."""

    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=t("The file is larger than 40 MB."))
    data = await request.body()
    sheets = rt.licence.limit("sheets")
    try:
        fields = DrawingFields(number=number, title=title, unit=unit)
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail=t("A drawing number like PID-U200-001.")
        ) from error
    existing = rt.drawings.store.by_number(fields.number) if fields.number else None
    if sheets is not None and existing is None and len(rt.drawings.list()) >= sheets:
        raise HTTPException(
            status_code=402,
            detail=t("The licence allows {n} drawings; ask its publisher for more.", n=sheets),
        )
    try:
        added = rt.drawings.add(data, filename, fields, user.username)
    except Refused as error:
        raise HTTPException(status_code=422, detail=t(str(error))) from error
    rt.audit(
        user, "drawing.send", added["drawing_id"], {"rev": added["rev_id"], "bytes": len(data)}
    )
    return added


@router.get("/drawings/{drawing_id}")
def get_drawing(rt: RuntimeDep, _user: CurrentUser, drawing_id: str = DrawingId) -> dict[str, Any]:
    drawing = drawing_or_404(rt, drawing_id)
    pages = [d for d in rt.store.diagrams() if d["doc_id"] == drawing_id]
    return {**drawing, "pages": pages}


@router.patch("/drawings/{drawing_id}")
def change_drawing(
    body: DrawingChange, rt: RuntimeDep, user: EditorUser, drawing_id: str = DrawingId
) -> dict[str, Any]:
    drawing_or_404(rt, drawing_id)
    rt.store.update_drawing(drawing_id, **body.model_dump(exclude_none=True))
    rt.audit(user, "drawing.change", drawing_id, body.model_dump(exclude_none=True))
    return drawing_or_404(rt, drawing_id)


@router.post("/drawings/{drawing_id}/read")
def read_again(rt: RuntimeDep, user: EditorUser, drawing_id: str = DrawingId) -> dict[str, Any]:
    """Reads the drawing's current file again now (after a reader update)."""

    drawing = drawing_or_404(rt, drawing_id)
    if not drawing.get("rev_id"):
        raise HTTPException(status_code=409, detail=t("This drawing has no file."))
    rt.drawings.read_one(drawing["rev_id"])
    rt.audit(user, "drawing.read", drawing_id)
    return drawing_or_404(rt, drawing_id)


@router.delete("/drawings/{drawing_id}")
def delete_drawing(
    rt: RuntimeDep, user: EditorUser, drawing_id: str = DrawingId
) -> dict[str, bool]:
    drawing = drawing_or_404(rt, drawing_id)
    rt.drawings.delete(drawing_id)
    rt.audit(user, "drawing.delete", drawing_id, {"number": drawing["number"]})
    return {"deleted": True}
