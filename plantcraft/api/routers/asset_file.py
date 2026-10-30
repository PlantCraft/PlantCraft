"""HTTP routes: the asset file (Assets › Export and Assets › Import).

Only the tree travels here: assets, their records, the signals they reference and their
relations (``plantcraft/platform/assetfile.py``). Data sources are the Historian's. An import is
read (``/read``, the file as the request body), reviewed and edited on its own page
(``/review``), then applied (``/apply``): the last two take the document as JSON. The newest
applied import can be undone (``/last-import``, ``/undo``).

A new plant's first tree can be drafted instead of written (``/draft``): from a
source's tags or a tag spreadsheet (``/draft/tags``), placed by the plant's documents when
PlantCraft Documents is installed and by a language model when one is chosen for "Plant draft"
(``plantcraft/platform/plantdraft.py``). The draft opens on the same review page.

Once an import is applied, the apps' first steps for the assets it wrote are offered
(``/start``, ``[[contributes.start]]``, D5 F4): collect their signals, monitor their loops, draft
their alarms, draw their overviews. Each is sent to its app as the administrator who takes it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from plantcraft.api import app_proxy as proxy
from plantcraft.api.deps import AdminUser, CurrentUser, Runtime
from plantcraft.api.routers.data import source_variables
from plantcraft.i18n import t
from plantcraft.platform import assetfile, plantdraft
from plantcraft.specialists.profiles import models_allowed_for

router = APIRouter(prefix="/api/asset-file")


@router.get("/formats")
def formats(_user: CurrentUser) -> list[dict[str, str]]:
    """The formats the tree is exported in and read from."""

    return [
        {
            "id": "json",
            "label": "JSON",
            "detail": t("PlantCraft's own: everything, read back exactly."),
        },
        {
            "id": "xlsx",
            "label": "Excel",
            "detail": t("Sheets assets, signals and relations, to edit by hand."),
        },
        {
            "id": "csv",
            "label": "CSV",
            "detail": t("One row per asset, a column per attribute and per signal role."),
        },
        {
            "id": "b2mml",
            "label": "ISA-95 B2MML",
            "detail": t(
                "Equipment hierarchy (EquipmentInformation), for MES and other ISA-95 tools."
            ),
        },
        {
            "id": "af",
            "label": "PI AF XML",
            "detail": t(
                "Elements, templates and PI Point attributes, as PI Asset Framework exports them."
            ),
        },
    ]


@router.get("/export.{kind}")
def export(
    kind: str,
    _user: CurrentUser,
    rt: Runtime,
    root: str | None = Query(default=None, max_length=128),
) -> Response:
    if kind not in assetfile.FORMATS:
        raise HTTPException(status_code=404, detail=t("Unknown format."))
    try:
        content, media, extension = assetfile.export(rt.platform, kind, root)
    except assetfile.AssetFileError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    name = f"assets-{root}" if root and root != rt.platform.root_asset_id else "assets"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}.{extension}"'},
    )


@router.post("/read")
async def read(
    request: Request,
    _user: AdminUser,
    rt: Runtime,
    filename: str = Query(min_length=1, max_length=200),
    anchor: str | None = Query(default=None, max_length=128),
) -> dict[str, Any]:
    """The file read into a document and reviewed: what each asset would become."""

    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail=t("Send the file."))
    try:
        document, notes = assetfile.read(content, filename)
        review = await run_in_threadpool(assetfile.review, rt.platform, document, anchor=anchor)
    except assetfile.AssetFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**review, "file": filename, "notes": notes}


def _document(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
        raise HTTPException(status_code=422, detail=t("Send a document with an assets list."))
    return payload


@router.post("/review")
async def review(
    _user: AdminUser, rt: Runtime, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """The document as the review page edited it, reviewed again."""

    try:
        return await run_in_threadpool(
            assetfile.review, rt.platform, _document(payload), anchor=payload.get("anchor")
        )
    except assetfile.AssetFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/apply")
async def apply(
    user: AdminUser, rt: Runtime, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Write the reviewed document; nothing is written while any included row has an error."""

    document = _document(payload)
    try:
        result = await run_in_threadpool(
            assetfile.apply, rt.platform, document, actor=user, anchor=payload.get("anchor")
        )
    except assetfile.AssetFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result["applied"] and (result["created"] or result["updated"]):
        rt.platform.publish(
            "assets.imported",
            f"asset:{rt.platform.root_asset_id}",
            source="platform",
            actor=user,
            summary=t(
                "Assets imported: {created} created, {updated} updated.",
                created=result["created"],
                updated=result["updated"],
            ),
        )
    return result


@router.get("/last-import")
def last_import(_user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The newest import (who, when, what it changed) and whether it can still be undone."""

    return {"import": assetfile.last_import(rt.platform)}


@router.post("/undo")
async def undo(user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Undo the newest import: what it created goes, what it overwrote comes back."""

    try:
        done = await run_in_threadpool(assetfile.undo_last, rt.platform, actor=user)
    except assetfile.AssetFileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**done, "import": assetfile.last_import(rt.platform)}


# Drafting a new plant ----------------------------------------------------------------

DOCUMENTS = "doccraft"
FIND_TAGS = "find_tags"
MODEL_USE = "plant-draft"


@router.get("/draft/options")
def draft_options(_user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """What a draft can read here: the sources, whether Documents and a model are there."""

    return {
        "documents": _documents_installed(rt),
        "model": rt.specialists.use_model(MODEL_USE) is not None and models_allowed_for("admin"),
    }


@router.post("/draft/tags")
async def draft_tags(
    request: Request,
    _user: AdminUser,
    filename: str = Query(min_length=1, max_length=200),
) -> dict[str, Any]:
    """The tags of a tag spreadsheet (CSV or Excel), to draft the plant from."""

    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail=t("Send the file."))
    try:
        tags, notes = plantdraft.tag_list(content, filename)
    except assetfile.AssetFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"tags": tags, "notes": notes, "file": filename}


@router.post("/draft")
async def draft(
    user: AdminUser, rt: Runtime, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """The plant drafted from a source's tags or the tags of a list, reviewed like a file."""

    source_id = str(payload.get("source_id") or "")
    if source_id:
        variables = await run_in_threadpool(source_variables, rt, source_id)
        tags = [
            {
                "tag": item["tag"],
                "description": item.get("description") or "",
                "eng_unit": item.get("unit") or "",
                "source_id": source_id,
            }
            for item in variables
        ]
        origin = t("Tags of source {source}", source=source_id)
    else:
        raw = payload.get("tags")
        if not isinstance(raw, list):
            raise HTTPException(status_code=422, detail=t("Choose a source or send a tag list."))
        tags = [item for item in raw[: plantdraft.MAX_TAGS] if isinstance(item, dict)]
        origin = str(payload.get("file") or t("Tag list"))[:200]
    if not tags:
        raise HTTPException(status_code=422, detail=t("There are no tags to draft from."))
    notes: list[str] = []
    find = _finder(rt, user, notes) if payload.get("documents", True) else None
    ask = _asker(rt, user, notes) if payload.get("model") else None
    anchor = payload.get("anchor") or None
    document, summary = await run_in_threadpool(
        lambda: plantdraft.draft(rt.platform, tags, find=find, ask=ask, anchor=anchor)
    )
    summary["documents"] = find is not None and not any("Documents" in note for note in notes)
    summary["model"] = ask is not None
    if summary.get("model_error"):
        notes.append(t("The language model did not answer: {error}", error=summary["model_error"]))
    if summary["dropped"]:
        notes.append(
            t(
                "{count} suggestions of the language model named what the sources do not; left out.",
                count=summary["dropped"],
            )
        )
    if summary["unrecognised"]:
        notes.append(
            t(
                "{count} tags are not loops or instruments by ISA-5.1 (for example {tags}); bind them by hand.",
                count=summary["unrecognised"],
                tags=", ".join(summary["unrecognised_examples"][:3]),
            )
        )
    rt.workspace.audit.record(
        user,
        "assets.drafted",
        "assets",
        {key: summary[key] for key in ("tags", "loops", "placed", "by_model", "dropped")}
        | {"documents": find is not None, "model": ask is not None},
    )
    try:
        review = await run_in_threadpool(assetfile.review, rt.platform, document, anchor=anchor)
    except assetfile.AssetFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**review, "file": origin, "notes": notes, "draft": summary}


def _documents_installed(rt: Any) -> bool:
    return rt.app_tools.find(DOCUMENTS, FIND_TAGS) is not None and DOCUMENTS in {
        app.id for app in rt.suite_apps()
    }


def _finder(rt: Any, user: str, notes: list[str]) -> plantdraft.Find | None:
    """Documents' find_tags, called as the person; after a failure the draft goes on without."""

    if not _documents_installed(rt):
        return None
    failed: list[str] = []

    def find(tags: list[str]) -> dict[str, list[dict[str, Any]]]:
        if failed:
            return {}
        try:
            answer = proxy.post_tool(rt, DOCUMENTS, FIND_TAGS, user, {"tags": ", ".join(tags)})
        except proxy.AppUnreachable:
            answer = None
        if answer is None or answer.status != 200:
            failed.append("x")
            notes.append(t("Documents did not answer; the draft is made without the documents."))
            return {}
        body = answer.json()
        found = body.get("tags") if isinstance(body, dict) else None
        return found if isinstance(found, dict) else {}

    return find


def _asker(rt: Any, user: str, notes: list[str]) -> Callable[[str, str], str] | None:
    found = rt.specialists.use_model(MODEL_USE)
    if found is None or not models_allowed_for("admin"):
        notes.append(
            t(
                'No language model is chosen for "Plant draft" (Settings › Language models); the draft uses rules and documents only.'
            )
        )
        return None
    model = rt.specialist_chat.model_factory(
        found["key"],
        provider=found["kind"],
        model=found["name"],
        endpoint=found["endpoint"],
        reasoning=found["reasoning"],
    )

    def ask(system: str, question: str) -> str:
        rt.workspace.audit.record(
            user, "assets.draft_model", "assets", {"model": found["name"], "chars": len(question)}
        )
        return model.answer(system, [{"role": "user", "content": question}])

    return ask


# The apps' first steps -------------------------------------------------------------


@router.get("/start")
def start_steps(_user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The first steps the installed apps take for the newest import, in the suite's order."""

    found = assetfile.last_import(rt.platform)
    if found is None or found["undone_at"] is not None:
        return {"import": found, "steps": []}
    apps = {app.id: app for app in rt.suite_apps()}
    steps = [
        {
            "app": row["app"],
            "app_name": apps[row["app"]].name,
            "id": step["id"],
            "title": step["title"],
            "description": step.get("description") or "",
            "default": bool(step.get("default", True)),
            "open": step.get("open"),
        }
        for row in rt.contributions.listing(list(apps))
        for step in (row.get("contributes") or {}).get("start") or []
    ]
    return {"import": found, "steps": steps}


@router.post("/start/{app}/{step_id}")
async def take_start_step(app: str, step_id: str, user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Take one app's first step for the newest import, as this administrator."""

    if app not in {item.id for item in rt.suite_apps()}:
        raise HTTPException(status_code=404, detail=t("That app is not installed."))
    row = rt.contributions.get(app) or {}
    declared = {step["id"] for step in (row.get("contributes") or {}).get("start") or []}
    if step_id not in declared:
        raise HTTPException(status_code=404, detail=t("That app has no such step."))
    scope = await run_in_threadpool(assetfile.start_scope, rt.platform)
    if scope is None:
        raise HTTPException(status_code=409, detail=t("There is no import to start from."))
    try:
        answer = await run_in_threadpool(proxy.post_start, rt, app, step_id, user, scope)
    except proxy.AppUnreachable as exc:
        raise HTTPException(status_code=502, detail=t("The app does not answer.")) from exc
    body = _json_or_none(answer)
    if answer.status >= 400:
        detail = body.get("detail") if isinstance(body, dict) else None
        raise HTTPException(
            status_code=502 if answer.status >= 500 else answer.status,
            detail=str(detail) if isinstance(detail, str) else t("The app refused the step."),
        )
    if not isinstance(body, dict) or not isinstance(body.get("summary"), str):
        raise HTTPException(status_code=502, detail=t("The app gave no answer."))
    done = {
        "summary": body["summary"][:600],
        "counts": {
            str(key): value
            for key, value in (body.get("counts") or {}).items()
            if isinstance(value, int)
        },
        "open": body.get("open") if isinstance(body.get("open"), str) else None,
    }
    rt.workspace.audit.record(
        user,
        "assets.start_step",
        f"{app}:{step_id}",
        {"import_id": scope["import_id"], "counts": done["counts"]},
    )
    return done


def _json_or_none(answer: proxy.Answer) -> Any:
    try:
        return answer.json()
    except ValueError:
        return None
