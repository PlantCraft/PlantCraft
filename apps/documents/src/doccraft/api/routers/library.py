"""HTTP routes: folders, documents, their files and passages, the reading queue and the search."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from plantcraft_sdk.server.queue import FORMAT as QUEUE_FORMAT
from plantcraft_sdk.server.queue import SAMPLE_SECONDS, QueueNow

from doccraft.api.deps import CurrentUser, EditorUser, RuntimeDep, document_or_404, editable_or_403
from doccraft.i18n import t
from doccraft.library.extract import Unreadable, format_of
from doccraft.library.models import (
    KINDS,
    DocumentAssets,
    DocumentFields,
    FolderPayload,
    SearchRequest,
)
from doccraft.library.preview import docx_html
from doccraft.library.service import Refused

router = APIRouter(prefix="/api", tags=["documents"])
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text": "text/plain; charset=utf-8",
    "markdown": "text/plain; charset=utf-8",
    "csv": "text/plain; charset=utf-8",
    "html": "text/plain; charset=utf-8",  # never rendered as a page
}


@router.get("/kinds")
def kinds(_user: CurrentUser) -> list[str]:
    return list(KINDS)


# Folders


@router.get("/folders")
def list_folders(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    perms = rt.permissions(user)
    return [
        {**folder, "can_edit": perms.edits_folder(folder["folder_id"])}
        for folder in rt.store.folders()
        if perms.sees_folder(folder["folder_id"])
    ]


@router.post("/folders", status_code=201)
def create_folder(payload: FolderPayload, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    if any(f["name"].casefold() == payload.name.casefold() for f in rt.store.folders()):
        raise HTTPException(status_code=409, detail=t("There is a folder with that name."))
    folder = rt.store.save_folder(None, payload.model_dump(), user.username)
    rt.audit(user, "folder.create", folder["folder_id"], payload.model_dump())
    return folder


@router.put("/folders/{folder_id}")
def update_folder(
    folder_id: str, payload: FolderPayload, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    perms = rt.permissions(user)
    if perms.folder(folder_id) is None or not perms.sees_folder(folder_id):
        raise HTTPException(status_code=404, detail=t("Folder not found."))
    if not perms.edits_folder(folder_id):
        raise HTTPException(status_code=403, detail=t("Only the editors of this folder change it."))
    folder = rt.store.save_folder(folder_id, payload.model_dump(), user.username)
    rt.audit(user, "folder.update", folder_id, payload.model_dump())
    return folder


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: str, rt: RuntimeDep, user: EditorUser) -> None:
    perms = rt.permissions(user)
    if perms.folder(folder_id) is None or not perms.sees_folder(folder_id):
        raise HTTPException(status_code=404, detail=t("Folder not found."))
    if not perms.edits_folder(folder_id):
        raise HTTPException(status_code=403, detail=t("Only the editors of this folder change it."))
    if not rt.store.delete_folder(folder_id):
        raise HTTPException(status_code=409, detail=t("Move or delete its documents first."))
    rt.audit(user, "folder.delete", folder_id)


# Documents


@router.get("/documents")
def list_documents(
    rt: RuntimeDep,
    user: CurrentUser,
    folder: str | None = Query(None, max_length=12),
    asset: str | None = Query(None, max_length=126),
    kind: str | None = Query(None, max_length=40),
) -> list[dict[str, Any]]:
    perms = rt.permissions(user)
    visible = perms.visible_folders()
    if folder is not None:
        visible &= {folder}
    assets = [asset.removeprefix("asset:")] if asset else None
    return perms.docs(rt.store.documents(visible, assets, kind))


@router.post("/documents", status_code=201)
async def send_document(
    request: Request,
    rt: RuntimeDep,
    user: EditorUser,
    filename: str = Query(..., min_length=1, max_length=200),
    folder: str = Query("", max_length=12),
    number: str = Query("", max_length=60),
    title: str = Query("", max_length=200),
    description: str = Query("", max_length=1000),
    kind: str = Query("Other", max_length=40),
    unit: str = Query("", max_length=60),
    language: str = Query("", max_length=10),
    revision: str = Query("", max_length=20),
    issued: str = Query("", max_length=10),
) -> dict[str, Any]:
    """The file is the request's body (any type); the description comes in the query."""

    fields = DocumentFields(
        folder_id=folder or None,
        number=number,
        title=title or None,
        description=description,
        kind=kind,
        unit=unit,
        language=language,
    )
    perms = rt.permissions(user)
    if folder and (perms.folder(folder) is None or not perms.sees_folder(folder)):
        raise HTTPException(status_code=404, detail=t("Folder not found."))
    if not perms.edits_folder(folder):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of this folder send documents to it.")
        )
    existing = rt.store.by_number(number)
    if existing is not None and not perms.edits_folder(existing["folder_id"]):
        raise HTTPException(
            status_code=403,
            detail=t("Document {number} is in a folder you do not change.", number=number),
        )
    limit = rt.library.max_bytes
    if int(request.headers.get("content-length") or 0) > limit:
        raise HTTPException(
            status_code=413, detail=t("The file is larger than {mb} MB.", mb=limit // 2**20)
        )
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(
                status_code=413, detail=t("The file is larger than {mb} MB.", mb=limit // 2**20)
            )
    values = fields.model_dump(exclude_none=True)
    values["folder_id"] = folder
    try:
        doc = rt.library.add(bytes(data), filename, values, revision, issued, user.username)
    except Refused as error:
        raise HTTPException(status_code=422, detail=t(str(error))) from error
    rt.audit(
        user,
        "document.send",
        doc["doc_id"],
        {"file": filename, "number": number, "revision": revision},
    )
    return doc


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    doc = document_or_404(rt, doc_id, user)
    return {**doc, "can_edit": rt.permissions(user).edits_folder(doc["folder_id"])}


@router.patch("/documents/{doc_id}")
def update_document(
    doc_id: str, fields: DocumentFields, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    editable_or_403(rt, doc_id, user)
    values = fields.model_dump(exclude_none=True)
    if "folder_id" in values and not rt.permissions(user).edits_folder(values["folder_id"]):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of a folder move documents into it.")
        )
    doc = rt.store.update(doc_id, values)
    rt.audit(user, "document.update", doc_id, values)
    return doc or {}


@router.put("/documents/{doc_id}/assets")
def set_assets(
    doc_id: str, payload: DocumentAssets, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    editable_or_403(rt, doc_id, user)
    rt.store.set_assets(doc_id, payload.assets)
    rt.audit(user, "document.assets", doc_id, {"assets": payload.assets})
    return rt.store.document(doc_id) or {}


@router.post("/documents/{doc_id}/reindex", status_code=202)
def reindex(doc_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    editable_or_403(rt, doc_id, user)
    if not rt.library.reindex(doc_id):
        raise HTTPException(status_code=409, detail=t("The document has no file to read."))
    return {"queued": True}


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, rt: RuntimeDep, user: EditorUser) -> None:
    doc = editable_or_403(rt, doc_id, user)
    rt.store.delete(doc_id)
    rt.audit(user, "document.delete", doc_id, {"number": doc["number"], "title": doc["title"]})


@router.get("/documents/{doc_id}/file")
def document_file(
    doc_id: str,
    rt: RuntimeDep,
    user: CurrentUser,
    revision: str | None = Query(None, max_length=12),
    inline: bool = Query(False),
) -> FileResponse:
    """The original file, always as an attachment except a PDF asked inline (the viewer)."""

    doc = document_or_404(rt, doc_id, user)
    rev = (
        next((r for r in doc["revisions"] if r["rev_id"] == revision), None)
        if revision
        else doc["current"]
    )
    if rev is None:
        raise HTTPException(status_code=404, detail=t("File not found."))
    path = rt.store.file_path(rev["sha256"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail=t("File not found."))
    rt.audit(user, "document.download", doc_id, {"revision": rev["rev_id"]})
    kind = rev["format"] or format_of(rev["filename"]) or ""  # known once read; else by its name
    show = inline and kind == "pdf"
    name = quote(rev["filename"])
    headers = {"X-Content-Type-Options": "nosniff"}
    if show:
        # The browser's own PDF viewer, in a tab of its own: a sandboxed PDF is refused by some
        # browsers, and a PDF never runs as a page of this origin.
        headers["Content-Disposition"] = f"inline; filename*=UTF-8''{name}"
    else:
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{name}"
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return FileResponse(
        path, media_type=MIME.get(kind, "application/octet-stream"), headers=headers
    )


@router.get("/documents/{doc_id}/view")
def document_view(doc_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    """A Word file as a page (``preview.docx_html``: its text in a fixed set of tags, escaped)."""

    doc = document_or_404(rt, doc_id, user)
    rev = doc["current"]
    if rev is None or (rev["format"] or format_of(rev["filename"])) != "docx":
        raise HTTPException(status_code=404, detail=t("Only Word files are shown as a page."))
    path = rt.store.file_path(rev["sha256"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail=t("File not found."))
    try:
        page = docx_html(path.read_bytes())
    except Unreadable as error:
        raise HTTPException(status_code=422, detail=t(str(error))) from error
    rt.audit(user, "document.view", doc_id, {"revision": rev["rev_id"]})
    return {"revision": rev["revision"], "filename": rev["filename"], "html": page}


@router.get("/documents/{doc_id}/passages")
def document_passages(
    doc_id: str, rt: RuntimeDep, user: CurrentUser, page: int | None = Query(None, ge=1, le=100000)
) -> list[dict[str, Any]]:
    doc = document_or_404(rt, doc_id, user)
    if not doc["current"]:
        return []
    return rt.store.passages(doc["current"]["rev_id"], page)


# Search and queue


def hits_answer(hits: list[Any], root: str, query: str = "") -> list[dict[str, Any]]:
    """Each passage found, with the page that opens it there (``q``: the words marked on it)."""

    words = f"&q={quote(query, safe='')}" if query else ""
    out = []
    for hit in hits:
        p = hit.passage
        page = p.get("page_from")
        out.append(
            {
                "ref": f"doc:{p['doc_id']}",
                "doc_id": p["doc_id"],
                "passage_id": p["passage_id"],
                "number": p["number"],
                "title": p["title"],
                "kind": p["kind"],
                "revision": p["revision"],
                "page": page,
                "pages": [p.get("page_from"), p.get("page_to")],
                "section": p["section"],
                "text": p["text"],
                "assets": p["assets"],
                "score": round(hit.score, 5),
                "found_by": hit.by,
                "url": f"{root}/documents/{p['doc_id']}?passage={p['passage_id']}"
                + (f"&page={page}" if page else "")
                + words,
            }
        )
    return out


@router.post("/search")
def search(payload: SearchRequest, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    perms = rt.permissions(user)
    folders = perms.visible_folders()
    if payload.folder is not None:
        folders &= {payload.folder}
    asset = payload.asset.removeprefix("asset:") if payload.asset else None
    hits = rt.library.search(
        payload.query,
        folders=folders,
        assets=[asset] if asset else None,
        kind=payload.kind,
        limit=payload.limit,
        scope=perms.scope,
    )
    return {
        "query": payload.query,
        "passages": hits_answer(hits, rt.settings.root_path, payload.query),
    }


@router.get("/queue")
def queue(rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    """The reading queue in the suite's format (``plantcraft-queue/1``), read by the Queue of
    the side bar (final round, 2026-10-27: no page of its own here): what waits and is being
    read now, each file waiting, read in the last day or that could not be read, and the
    library's counts. Only what the person may see."""

    perms = rt.permissions(user)
    visible = perms.visible_folders()
    docs = {d["doc_id"] for d in perms.docs(rt.store.documents(visible))}
    rows = [item for item in rt.store.queue(since=_hours_ago(24)) if item["doc_id"] in docs]
    counts = rt.store.counts(visible)
    waiting = [row for row in rows if row["status"] == "queued"]
    oldest = min((row["uploaded_at"] for row in waiting), default=None)
    hour = _hours_ago(1)
    now = QueueNow(
        queued=len(waiting),
        running=sum(1 for row in rows if row["status"] == "indexing"),
        workers=1,
        busy=1 if any(row["status"] == "indexing" for row in rows) else 0,
        done_hour=sum(
            1 for row in rows if row["status"] == "indexed" and row["indexed_at"] >= hour
        ),
        failed_hour=sum(
            1 for row in rows if row["status"] == "failed" and row["uploaded_at"] >= hour
        ),
        delay_seconds=_seconds_since(oldest) if oldest else 0.0,
    )
    root = rt.settings.root_path
    return {
        "format": QUEUE_FORMAT,
        "window": "1h",
        "sample_seconds": SAMPLE_SECONDS,
        "now": now.as_dict(),
        "history": [],
        "url": "documents",
        "items": [_queue_item(row, root) for row in rows],
        **counts,
        "embedder": rt.library.embedder.name,
    }


QUEUE_STATUS = {"queued": "queued", "indexing": "running", "indexed": "done", "failed": "failed"}


def _queue_item(row: dict[str, Any], root: str) -> dict[str, Any]:
    name = " · ".join(part for part in (row["number"], row["title"]) if part)
    return {
        "id": row["rev_id"],
        "name": name or row["filename"],
        "by": row["uploaded_by"],
        "status": QUEUE_STATUS.get(row["status"], row["status"]),
        "progress": None,
        "step": row["error"] if row["status"] == "failed" else row["filename"],
        "url": f"{root}/documents/{row['doc_id']}",
        "started_at": row["uploaded_at"],
        "finished_at": row["indexed_at"],
        "cancel": None,
        "doc_id": row["doc_id"],
        "filename": row["filename"],
    }


def _hours_ago(hours: float) -> str:
    moment = datetime.now(UTC) - timedelta(hours=hours)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _seconds_since(stamp: str) -> float:
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - moment).total_seconds())
