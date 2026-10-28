"""Models drawn as block diagrams: the catalog of blocks, the models, their diagram and settings,
and a run of a model with its own settings.

A model is a Modelica class; a new one is a project of its own (one file), so a person's
models never share text. The diagram and the simulation settings are read from the class's
text and written back to it (``modelica.blockdiagram``); the code stays one click away for
whatever the diagram cannot hold.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from plantcraft_sdk.images import MAX_IMAGE_BYTES, ImageError, image_response, image_tag
from plantcraft_sdk.images import block_image as checked_image
from pydantic import BaseModel, ConfigDict, Field

from modelcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, project_or_404
from modelcraft.api.routers.model import _workbench_error
from modelcraft.api.routers.projects import _identifier, _refused
from modelcraft.api.runtime import BLOCK_EXAMPLES
from modelcraft.i18n import t
from modelcraft.modelica import blockdiagram
from modelcraft.modelica.declarations import class_elements, modelica_value
from modelcraft.modelica.edit import EditError, rename_class, set_binding, set_image
from modelcraft.modelica.interface import interface, library_blocks
from modelcraft.modelica.source import find
from modelcraft.projects.models import MAX_DESCRIPTION, MAX_GROUP, ProjectError, ReadOnly
from modelcraft.runs.service import WorkbenchError, project_classes

router = APIRouter(prefix="/api", tags=["models"])
MAX_LABEL = 120


class NewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    group: str = Field(default="", max_length=MAX_GROUP)


class ImportedModel(BaseModel):
    """A model in a Modelica file from the person's computer (round 9: New model, Import)."""

    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=4, max_length=200, pattern=r"^[^/\\]+\.mo$")
    text: str = Field(min_length=1, max_length=2_000_000)
    group: str = Field(default="", max_length=MAX_GROUP)


class ModelChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    group: str | None = Field(default=None, max_length=MAX_GROUP)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float
    stop: float
    interval: float
    tolerance: float
    solver: str = Field(max_length=20)


class DiagramBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagram: dict[str, Any]
    settings: Settings | None = None
    base_updated_at: str | None = Field(default=None, max_length=64)
    # The version this save makes: its name and what changed (as Link's algorithms).
    version_name: str = Field(default="", max_length=120)
    version_note: str = Field(default="", max_length=2000)


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=MAX_LABEL)


class CompareBody(BaseModel):
    """Versions of a model run on the same simulation settings (round 9 M4): each a revision id of its
    file, 0 for the version in use, with the label its run carries ("Version 3")."""

    model_config = ConfigDict(extra="forbid")

    revisions: list[int] = Field(min_length=2, max_length=3)
    labels: list[str] = Field(default_factory=list, max_length=3)


# The catalog -------------------------------------------------------------------------------

_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


def catalog(rt) -> dict[str, dict[str, Any]]:
    """Every block of the libraries, by its class name (read again when a library changes)."""

    libraries = rt.projects.list("library")
    digest = hashlib.sha256()
    for library in libraries:
        digest.update(f"{library['id']}\0{library['name']}\0{library['updated_at']}\0".encode())
    key = digest.hexdigest()
    with _CACHE_LOCK:
        if _CACHE.get("key") == key:
            return _CACHE["blocks"]
    found: dict[str, dict[str, Any]] = {}
    for library in libraries:
        files = rt.projects.files(library["id"])
        for spec in library_blocks(files, library=library["id"], library_name=library["name"]):
            found.setdefault(spec["block_id"], {**spec, "group": library.get("block_group", "")})
    with _CACHE_LOCK:
        _CACHE.update(key=key, blocks=found)
    return found


@router.get("/catalog")
def list_catalog(rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    """The blocks a model's diagram may use, by library, in the format of the suite's block
    editor (``@plantcraft/ui`` ``BlockCatalog``)."""

    blocks = [_pictured(block) for block in catalog(rt).values()]
    libraries = [
        {
            "library": library["id"],
            "name": library["name"],
            "description": library["description"],
            "group": library.get("block_group", ""),
            # The site's own library: its blocks go in folders (round 9, M5).
            "own": not library["example"],
            "count": sum(1 for block in blocks if block["library"] == library["id"]),
        }
        for library in rt.projects.list("library")
    ]
    # The shipped libraries in the order a diagram is drawn: sources, math, dynamics, control,
    # equipment, then the scopes; a person's own libraries after them, by group and name.
    shipped = [name for name, _, _ in BLOCK_EXAMPLES.values()]
    libraries.sort(
        key=lambda item: (
            shipped.index(item["name"]) if item["name"] in shipped else len(shipped),
            item["group"].lower(),
            item["name"].lower(),
        )
    )
    return {"libraries": [item for item in libraries if item["count"]], "blocks": blocks}


def _pictured(block: dict[str, Any], revision_id: int = 0) -> dict[str, Any]:
    """A block as a page reads it: ``image`` is the path of its picture (round 9 M2), tagged
    with its content so a new picture is a new URL, never the picture (a catalog stays small)."""

    image = block.get("image") or ""
    if not image:
        return {**block, "image": None}
    base = f"/api/catalog/{quote(block['block_id'], safe='.')}"
    at = f"/versions/{revision_id}" if revision_id else ""
    return {**block, "image": f"{base}{at}/image?v={image_tag(image)}"}


class BlockImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A data URL (PNG, JPEG, WebP or SVG of at most 256 KB); "" takes the picture out.
    image: str = Field(max_length=MAX_IMAGE_BYTES * 4 // 3 + 200)
    base_updated_at: str | None = None


@router.get("/catalog/{block_id}/image")
def block_image_file(block_id: str, rt: RuntimeDep, _user: CurrentUser) -> Response:
    found = catalog(rt).get(block_id)
    if found is None or not found.get("image"):
        raise HTTPException(404, t("This block has no image."))
    return image_response(found["image"])


@router.put("/catalog/{block_id}/image")
def set_block_image(
    block_id: str, body: BlockImage, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """Put a picture on a block of the site's own library, or take it out: it is written in the
    class's ``Icon`` annotation (a ``Bitmap``), so it is saved with the file as a new version."""

    current = get_block(block_id, rt, user)
    if current["example"]:
        raise _refused(
            ReadOnly(t("A block Models ships keeps its picture: duplicate its library."))
        )
    try:
        image = checked_image(body.image)
    except ImageError as exc:
        raise HTTPException(422, str(exc)) from exc
    stored = rt.projects.file(current["library"], current["file"]) or {}
    try:
        text = set_image(current["code"], block_id, image)
        rt.projects.save_file(
            current["library"],
            current["file"],
            text,
            by=user.username,
            base_updated_at=body.base_updated_at or stored.get("updated_at"),
        )
    except (ProjectError, EditError) as exc:
        raise _refused(exc) from exc
    rt.audit(
        user,
        "block.image_set" if image else "block.image_removed",
        f"project:{current['library']}",
        {"block": block_id},
    )
    return get_block(block_id, rt, user)


@router.get("/catalog/{block_id}")
def get_block(block_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    found = catalog(rt).get(block_id)
    if found is None:
        raise HTTPException(404, t("Block not found."))
    library = rt.projects.get(found["library"]) or {}
    files = rt.projects.files(found["library"]) if library else {}
    item = next((c for c in project_classes(files) if c["name"] == block_id), None)
    stored = (rt.projects.file(found["library"], item["file"]) if item else None) or {}
    return {
        # The version in use: who saved it, when, and what changed (as a model's).
        "updated_at": None if library.get("example") else stored.get("updated_at"),
        "updated_by": None if library.get("example") else stored.get("updated_by"),
        "version_name": stored.get("version_name") or "",
        "version_note": stored.get("version_note") or "",
        **_pictured(found),
        "library_name": library.get("name", ""),
        "library_group": library.get("block_group", ""),
        "example": bool(library.get("example")),
        "file": item["file"] if item else "",
        "code": files.get(item["file"], "") if item else "",
    }


class BlockDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A parameter's new default, by its name (a number, a boolean, a list or an expression).
    values: dict[str, Any] = Field(min_length=1, max_length=200)
    # What changed is asked every time (owner, 2026-10-27); the name is optional.
    version_name: str = Field(default="", max_length=120)
    version_note: str = Field(min_length=1, max_length=2000)
    base_updated_at: str | None = Field(default=None, max_length=64)


@router.put("/catalog/{block_id}/defaults")
def set_block_defaults(
    block_id: str, body: BlockDefaults, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """Change the defaults of a block of the site's own library: written in its parameters'
    declarations, so the save is a new version of its file, with what changed. A model that
    sets its own value keeps it (defaults in cascade: block, model, study)."""

    current = get_block(block_id, rt, user)
    if current["example"]:
        raise _refused(ReadOnly(t("A block Models ships keeps its defaults: duplicate it.")))
    known = {item["name"] for item in current["parameters"]}
    unknown = sorted(set(body.values) - known)
    if unknown:
        raise HTTPException(422, t("{name} is not a parameter of this block.", name=unknown[0]))
    if not body.version_note.strip():
        raise HTTPException(422, t("Say what changed in this version."))
    stored = rt.projects.file(current["library"], current["file"]) or {}
    try:
        text = current["code"]
        for name, value in body.values.items():
            text = set_binding(text, block_id, name, modelica_value(value))
        rt.projects.save_file(
            current["library"],
            current["file"],
            text,
            by=user.username,
            base_updated_at=body.base_updated_at or stored.get("updated_at"),
            version_name=body.version_name,
            version_note=body.version_note,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (ProjectError, EditError) as exc:
        raise _refused(exc) from exc
    rt.audit(
        user,
        "block.defaults_set",
        f"project:{current['library']}",
        {"block": block_id, "parameters": sorted(body.values)},
    )
    return get_block(block_id, rt, user)


class BlockCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)


# Where a duplicated block goes when the site has no library of its own yet.
SITE_LIBRARY = ("SiteBlocks", "This site's blocks")


@router.post("/catalog/{block_id}/duplicate", status_code=201)
def duplicate_block(
    block_id: str, body: BlockCopy, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """A copy of any block, the ones Models ships too, in the site's own library (the first
    one, made when there is none) under a new name: changed there like any site block."""

    current = get_block(block_id, rt, user)
    found = find(current["code"], block_id)
    if found is None:
        raise HTTPException(404, t("Block not found."))
    own = [item for item in rt.projects.list("library") if not item["example"]]
    if own:
        library = own[0]
    else:
        package, name = SITE_LIBRARY
        library = rt.projects.create(
            t(name),
            by=user.username,
            files={
                f"{package}/package.mo": f'within;\npackage {package} "{t(name)}"\nend {package};\n'
            },
            kind="library",
        )
    files = rt.projects.files(library["id"])
    package = sorted({path.split("/")[0].removesuffix(".mo") for path in files})[0]
    short = _identifier(body.name)[:60]
    taken = {cls["short"] for cls in project_classes(files)}
    base, number = short, 2
    while short in taken:
        short, number = f"{base}{number}", number + 1
    text = rename_class(
        current["code"][found.start : found.end], found.short, short, within=package
    )
    if found.comment:
        text = text.replace(
            f'"{found.comment}"',
            f'"{body.name.replace(chr(34), "")}: {current["summary"].replace(chr(34), "")}"',
            1,
        )
    try:
        rt.projects.save_file(
            library["id"],
            f"{package}/{short}.mo",
            text + "\n",
            by=user.username,
            version_name="",
            version_note=t("Duplicated from {block}.", block=block_id),
        )
        order = files.get(f"{package}/package.order")
        if order is not None:
            rt.projects.save_file(
                library["id"],
                f"{package}/package.order",
                order.rstrip("\n") + f"\n{short}\n",
                by=user.username,
            )
    except (ProjectError, EditError) as exc:
        raise _refused(exc) from exc
    rt.audit(
        user,
        "block.duplicated",
        f"project:{library['id']}",
        {"from": block_id, "block": f"{package}.{short}"},
    )
    return get_block(f"{package}.{short}", rt, user)


def _block_at(rt, block_id: str, revision_id: int, user) -> tuple[dict, dict, dict | None]:
    """(the block now, the revision of its file, the block as that revision had it or None)."""

    current = get_block(block_id, rt, user)
    revision = _revision(rt, current["library"], current["file"], revision_id)
    files = {**rt.projects.files(current["library"]), current["file"]: revision["content"]}
    blocks = library_blocks(files, library=current["library"], library_name=current["library_name"])
    found = next((block for block in blocks if block["block_id"] == block_id), None)
    return current, revision, found


@router.get("/catalog/{block_id}/versions/{revision_id}")
def get_block_version(
    block_id: str, revision_id: int, rt: RuntimeDep, _user: CurrentUser
) -> dict[str, Any]:
    """A block as an earlier save of its library file had it (round 9 M3: compare versions):
    its ports and parameters, and the file's code then."""

    _, revision, found = _block_at(rt, block_id, revision_id, _user)
    return {
        **(
            _pictured(found, revision_id)
            if found
            else {
                "block_id": block_id,
                "inputs": [],
                "outputs": [],
                "parameters": [],
                "image": None,
            }
        ),
        "missing": found is None,
        "code": revision["content"],
        "revision": revision_id,
        "saved_by": revision["saved_by"],
        "saved_at": revision["saved_at"],
    }


@router.get("/catalog/{block_id}/versions/{revision_id}/image")
def block_version_image(
    block_id: str, revision_id: int, rt: RuntimeDep, _user: CurrentUser
) -> Response:
    _, _, found = _block_at(rt, block_id, revision_id, _user)
    if found is None or not found.get("image"):
        raise HTTPException(404, t("This block has no image."))
    return image_response(found["image"])


def _revision(rt, project_id: str, path: str, revision_id: int) -> dict[str, Any]:
    """An earlier content of one file (``file_revisions``), or 404."""

    found = rt.projects.revision(project_id, revision_id) if 0 < revision_id < 2**62 else None
    if found is None or found["path"] != path:
        raise HTTPException(404, t("Version not found."))
    return found


@router.get("/catalog/{block_id}/used-by")
def block_used_by(block_id: str, rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    """The models whose diagram places this block, and how many times (a block's Used by)."""

    if block_id not in catalog(rt):
        raise HTTPException(404, t("Block not found."))
    found = []
    for project in rt.projects.list():
        files = rt.projects.files(project["id"])
        classes = project_classes(files)
        for item in classes:
            if item["restriction"] != "model" or block_id not in files.get(item["file"], ""):
                continue
            found_elements = class_elements(files[item["file"]], item["name"])
            count = sum(
                1
                for declaration in (found_elements.declarations if found_elements else [])
                if declaration.type == block_id
            )
            if count:
                found.append(
                    {
                        "project_id": project["id"],
                        "model": item["name"],
                        "name": _name(project, item, classes),
                        "example": project["example"],
                        "count": count,
                    }
                )
    return sorted(found, key=lambda m: (not m["example"], m["name"].lower()))


# Models ------------------------------------------------------------------------------------


def _name(project: dict[str, Any], item: dict[str, Any], classes: list[dict[str, Any]]) -> str:
    """What a person calls the model: the name they gave it (its project's, when the project
    holds this model alone, as New model and Duplicate make it), else the class's own."""

    models = [c for c in classes if c["restriction"] == "model"]
    if not project["example"] and len(models) == 1:
        return project["name"]
    return item["short"]


def _models_of(project: dict[str, Any], files: dict[str, str], blocks) -> list[dict[str, Any]]:
    found = []
    classes = project_classes(files)
    for item in classes:
        if item["restriction"] != "model" or not item["simulable"]:
            continue
        text = files.get(item["file"], "")
        try:
            read = blockdiagram.read(text, item["name"], blocks)
        except EditError:
            continue
        found.append(
            {
                "project_id": project["id"],
                "project": project["name"],
                "group": project.get("block_group", ""),
                "example": project["example"],
                "model": item["name"],
                "name": _name(project, item, classes),
                "description": item["comment"],
                "file": item["file"],
                "diagram": read["editable"],
                "blocks": len(read["diagram"]["nodes"]),
                "settings": read["settings"],
                "updated_by": project["updated_by"],
                "updated_at": project["updated_at"],
            }
        )
    return found


@router.get("/models")
def list_models(rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    """Every model: the examples first, then by name."""

    blocks = catalog(rt)
    found = []
    for project in rt.projects.list():
        found += _models_of(project, rt.projects.files(project["id"]), blocks)
    return sorted(found, key=lambda m: (not m["example"], m["name"].lower()))


def _model_or_404(rt, project_id: str, model: str) -> tuple[dict, dict[str, Any], str, list]:
    project = project_or_404(rt, project_id)
    files = rt.projects.files(project_id)
    classes = project_classes(files)
    item = next((c for c in classes if c["name"] == model and c["restriction"] == "model"), None)
    if item is None:
        raise HTTPException(404, t("Model not found."))
    return project, item, files[item["file"]], classes


def _code_block(text: str, item: dict[str, Any], name: str) -> dict[str, Any] | None:
    """A model written as code, as the one block of its diagram (owner, 2026-10-24: one kind of
    model): its real inputs and outputs are its ports, its public parameters its settings."""

    found = class_elements(text, item["name"])
    if found is None:
        return None
    ports = interface(found)
    return {
        "block_id": f"modelica:{item['name']}",
        "library": "modelica",
        "group": "Modelica",
        "name": name,
        "summary": t("Written in Modelica code."),
        "description": item["comment"],
        "reading": "",
        "assumptions": [],
        "limitations": [],
        "formula": None,
        "references": [],
        "inputs": ports["inputs"],
        "outputs": ports["outputs"],
        "parameters": ports["parameters"],
    }


def _model(rt, project_id: str, model: str, revision_id: int = 0) -> dict[str, Any]:
    """The model as its page shows it; ``revision_id``: as an earlier save had it (round 9 M4)."""

    project, item, text, classes = _model_or_404(rt, project_id, model)
    if revision_id:
        text = _revision(rt, project_id, item["file"], revision_id)["content"]
        then = project_classes({item["file"]: text})
        item = next((c for c in then if c["name"] == model), item)
    read = blockdiagram.read(text, model, catalog(rt))
    file = rt.projects.file(project_id, item["file"]) or {}
    name = _name(project, item, classes)
    return {
        "project_id": project_id,
        "project": project["name"],
        "group": project.get("block_group", ""),
        "example": project["example"],
        "model": model,
        "name": name,
        "description": item["comment"],
        "file": item["file"],
        "updated_at": file.get("updated_at"),
        "updated_by": file.get("updated_by"),
        "version_name": file.get("version_name") or "",
        "version_note": file.get("version_note") or "",
        **read,
        "code_block": None if read["editable"] else _code_block(text, item, name),
        "revision": revision_id or None,
    }


def _new_project(
    rt, name: str, description: str, group: str, by: str, text_for
) -> tuple[dict, str]:
    ident = _identifier(name)[:60]
    try:
        project = rt.projects.create(
            name,
            by=by,
            description=description,
            files={f"{ident}.mo": text_for(ident)},
            group=group,
        )
    except (ProjectError, EditError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return project, ident


@router.post("/models", status_code=201)
def create_model(body: NewModel, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """A new, empty diagram model (a project of its own)."""

    project, ident = _new_project(
        rt,
        body.name,
        body.description,
        body.group,
        user.username,
        lambda ident: blockdiagram.new_model(ident, body.description),
    )
    rt.audit(user, "model.created", f"project:{project['id']}", {"model": ident})
    return _model(rt, project["id"], ident)


@router.post("/models/import", status_code=201)
def import_model(body: ImportedModel, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """A model read from a ``.mo`` file: a project of its own holding the file as it is, opened
    on its first model class (a diagram when PlantCraft can draw it, else one block of code)."""

    found = [
        item
        for item in project_classes({body.file_name: body.text})
        if item["restriction"] == "model"
    ]
    if not found:
        raise HTTPException(422, t("The file has no Modelica model in it."))
    item = found[0]
    try:
        project = rt.projects.create(
            str(item.get("comment") or item["name"].split(".")[-1])[:120],
            by=user.username,
            description=str(item.get("comment") or "")[:MAX_DESCRIPTION],
            files={body.file_name: body.text},
            group=body.group,
        )
    except ProjectError as exc:
        raise HTTPException(422, str(exc)) from exc
    rt.audit(user, "model.imported", f"project:{project['id']}", {"model": item["name"]})
    return _model(rt, project["id"], item["name"])


@router.get("/models/{project_id}/{model}")
def get_model(project_id: str, model: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    return _model(rt, project_id, model)


@router.put("/models/{project_id}/{model}")
def save_model(
    project_id: str, model: str, body: DiagramBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """Write the diagram (and the settings) into the model's text."""

    _, item, text, _ = _model_or_404(rt, project_id, model)
    try:
        text = blockdiagram.write(text, model, body.diagram, catalog(rt))
        if body.settings is not None:
            text = blockdiagram.set_settings(text, model, body.settings.model_dump())
    except EditError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        rt.projects.save_file(
            project_id,
            item["file"],
            text,
            by=user.username,
            base_updated_at=body.base_updated_at,
            version_name=body.version_name,
            version_note=body.version_note,
        )
    except ProjectError as exc:
        raise _refused(exc) from exc
    rt.audit(
        user, "model.saved", f"project:{project_id}", {"model": model, "name": body.version_name}
    )
    return _model(rt, project_id, model)


@router.patch("/models/{project_id}/{model}")
def change_model(
    project_id: str, model: str, body: ModelChange, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """The model's name, description and group (kept on its project)."""

    _model_or_404(rt, project_id, model)
    try:
        rt.projects.update(
            project_id,
            by=user.username,
            name=body.name,
            description=body.description,
            group=body.group,
        )
    except ProjectError as exc:
        raise _refused(exc) from exc
    return _model(rt, project_id, model)


@router.post("/models/{project_id}/{model}/duplicate", status_code=201)
def duplicate_model(
    project_id: str, model: str, body: NewModel, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """A copy of the model's diagram and settings, as a new model of the person's own."""

    current = _model(rt, project_id, model)
    if not current["editable"]:
        raise HTTPException(
            422, t("Only a model drawn as a diagram can be duplicated here: copy its code.")
        )

    def text_for(ident: str) -> str:
        text = blockdiagram.new_model(ident, body.description or current["description"])
        text = blockdiagram.write(text, ident, current["diagram"], catalog(rt))
        return blockdiagram.set_settings(text, ident, current["settings"])

    project, ident = _new_project(
        rt,
        body.name,
        body.description or current["description"],
        body.group or current["group"],
        user.username,
        text_for,
    )
    rt.audit(user, "model.created", f"project:{project['id']}", {"model": ident, "from": model})
    return _model(rt, project["id"], ident)


@router.delete("/models/{project_id}/{model}", status_code=204)
def delete_model(project_id: str, model: str, rt: RuntimeDep, user: EditorUser) -> None:
    """Delete a model with its project (its runs and studies stay in Executions)."""

    project, _, _, _ = _model_or_404(rt, project_id, model)
    if project["example"]:
        raise _refused(ReadOnly(t("Examples stay: duplicate one to change it.")))
    others = [
        c
        for c in project_classes(rt.projects.files(project_id))
        if c["simulable"] and c["name"] != model and c["restriction"] == "model"
    ]
    if others:
        raise HTTPException(
            409, t("{model} shares its code with other models: delete it in the code.", model=model)
        )
    if any(
        run["status"] in ("queued", "running")
        for run in rt.runs.list(project_id=project_id, limit=5000)
    ):
        raise HTTPException(409, t("Simulations of this model are still going: cancel them first."))
    try:
        rt.projects.delete(project_id, by=user.username)
    except ProjectError as exc:
        raise _refused(exc) from exc
    rt.folders.forget("model", f"{project_id}/{model}")
    rt.audit(
        user, "model.deleted", f"project:{project_id}", {"model": model, "name": project["name"]}
    )


@router.get("/models/{project_id}/{model}/versions/{revision_id}")
def model_version(
    project_id: str, model: str, revision_id: int, rt: RuntimeDep, _user: CurrentUser
) -> dict[str, Any]:
    """The model as an earlier save had it: its diagram, inputs and settings, read-only."""

    try:
        return _model(rt, project_id, model, revision_id)
    except EditError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/models/{project_id}/{model}/versions/{revision_id}/use")
def use_model_version(
    project_id: str, model: str, revision_id: int, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """Use this version: its text is saved again as the newest version (nothing is lost)."""

    project, item, _, _ = _model_or_404(rt, project_id, model)
    if project["example"]:
        raise _refused(ReadOnly(t("Examples stay: duplicate one to change it.")))
    revision = _revision(rt, project_id, item["file"], revision_id)
    current = rt.projects.file(project_id, item["file"]) or {}
    try:
        rt.projects.save_file(
            project_id,
            item["file"],
            revision["content"],
            by=user.username,
            base_updated_at=current.get("updated_at"),
            version_name=revision.get("version_name") or "",
            version_note=t("Saved again from an earlier version."),
        )
    except ProjectError as exc:
        raise _refused(exc) from exc
    rt.audit(
        user, "model.version_used", f"project:{project_id}", {"model": model, "from": revision_id}
    )
    return _model(rt, project_id, model)


@router.post("/models/{project_id}/{model}/compare", status_code=201)
def compare_versions(
    project_id: str, model: str, body: CompareBody, rt: RuntimeDep, user: EditorUser
) -> list[dict[str, Any]]:
    """Run two or three versions on the same simulation settings: the settings of the version in use,
    each version's own text (round 9 M4). One run per version, labelled as asked."""

    current = _model(rt, project_id, model)
    try:
        options = {**blockdiagram.run_options(current["settings"]), "overrides": {}}
    except EditError as exc:
        raise HTTPException(422, str(exc)) from exc
    runs = []
    for index, revision_id in enumerate(body.revisions):
        old = _revision(rt, project_id, current["file"], revision_id) if revision_id else None
        label = body.labels[index] if index < len(body.labels) else ""
        try:
            runs.append(
                rt.workbench.start(
                    project_id,
                    model,
                    "simulate",
                    options,
                    by=user.username,
                    label=label[:MAX_LABEL],
                    replace={current["file"]: old["content"]} if old else None,
                )
            )
        except WorkbenchError as exc:
            raise _workbench_error(exc) from exc
    rt.audit(
        user,
        "model.compared",
        f"project:{project_id}",
        {"model": model, "runs": [run["id"] for run in runs]},
    )
    return runs


@router.post("/models/{project_id}/{model}/run", status_code=201)
def run_model(
    project_id: str, model: str, body: RunBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """Simulate the model with its own settings (start, stop, step, tolerance, solver)."""

    current = _model(rt, project_id, model)
    try:
        options = {**blockdiagram.run_options(current["settings"]), "overrides": {}}
    except EditError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        run = rt.workbench.start(
            project_id, model, "simulate", options, by=user.username, label=body.label
        )
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc
    rt.audit(user, "run.started", f"project:{project_id}", {"run": run["id"], "model": model})
    return run
