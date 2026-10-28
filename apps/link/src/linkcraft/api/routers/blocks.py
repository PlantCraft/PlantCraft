"""Blocks: the catalog, each block's code and versions, and the blocks written on the site.

A block Link ships is read-only: its code is shown, and people copy it to change it. A site block
(``blocks.files``) is a block file with its Python code; every save is a new, immutable version
with a name and a description, and algorithms name the version they use. Writing block code is
for administrators (the code runs on the server, ``blocks.sandbox``); reading is for everyone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response
from plantcraft_sdk.blocks import block_markdown, describe_block
from plantcraft_sdk.images import image_response
from pydantic import BaseModel, Field

from linkcraft.api.deps import AdminUser, CurrentUser, EditorUser, RuntimeDep, admin
from linkcraft.assets.run import AssetTiming, block_diagram, run_on_asset, window_end
from linkcraft.blocks import CATALOG, catalog_items, compile_algorithm, libraries
from linkcraft.blocks import site as site_blocks
from linkcraft.blocks.catalog import BUILTIN_IDS, CURRENT
from linkcraft.blocks.convert import diagram_of
from linkcraft.blocks.files import (
    OPEN_LIBRARIES,
    BlockFile,
    file_of_spec,
    pinned_id,
    read_file,
    split_pinned,
)
from linkcraft.blocks.sandbox import ALLOWED_MODULES, check_code
from linkcraft.blocks.sources import COPYABLE, copy_file, edit_file, shipped_sources
from linkcraft.engine.suite_compute import interactive
from linkcraft.i18n import t

router = APIRouter(prefix="/api/blocks", tags=["blocks"])
SHIPPED_AUTHOR = "PlantCraft"


class FilePayload(BaseModel):
    file: dict[str, Any] | str


class SavePayload(FilePayload):
    version_name: str = Field(default="", max_length=120)
    version_description: str = Field(default="", max_length=2000)


class VersionPayload(FilePayload):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class SelectPayload(BaseModel):
    number: int = Field(ge=1)


class MetaPayload(BaseModel):
    owner: str | None = Field(default=None, max_length=120)
    owner_name: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=20)


class BlockTestPayload(FilePayload):
    """Run a block (a draft file or a saved version) on one asset's window."""

    asset_id: str = Field(min_length=1, max_length=200)
    # Each series or state input: a role of the asset (pv, sp…) or a signal id.
    roles: dict[str, str] = Field(default_factory=dict)
    signals: dict[str, str] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    timing: AssetTiming | None = None
    # The end of the window (a past upset, say); now when not given.
    end: datetime | None = None


def _site_meta(rt: Any) -> dict[str, dict[str, Any]]:
    return {item["block_id"]: item for item in rt.blocks.list()}


def _meta(block_id: str, sites: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Who made a block and what it is, beside its contract (the same keys for every block)."""

    pinned = split_pinned(block_id)
    if not pinned and block_id in sites:
        # A block Link ships whose version in use on the site is Link's own (version 1).
        pinned = (block_id, 1)
    if pinned and pinned[0] in sites:
        item = sites[pinned[0]]
        return {
            "family": item["block_id"],
            "number": pinned[1],
            "current": CURRENT.get(item["block_id"], item["block_id"]) == block_id,
            "origin": item["origin"],
            "author": item["author"],
            "author_name": item["author_name"] or item["author"],
            "owner": item["owner"],
            "owner_name": item["owner_name"] or item["owner"],
            "tags": item["tags"],
            "site": True,
            "updated_at": item["updated_at"],
        }
    model = block_id.startswith("model.fmu_")
    return {
        "family": block_id,
        "number": None,
        "current": True,
        "origin": "modelcraft-fmu" if model else "plantcraft",
        "author": SHIPPED_AUTHOR,
        "author_name": SHIPPED_AUTHOR,
        "owner": SHIPPED_AUTHOR,
        "owner_name": SHIPPED_AUTHOR,
        "tags": [],
        "site": False,
        "copyable": block_id in BUILTIN_IDS and block_id.split(".")[0] in COPYABLE,
        "updated_at": None,
    }


def _resolve(block_id: str) -> str:
    """The catalog id a page asks for: a site block's id opens its current version."""

    return CURRENT.get(block_id, block_id)


def _usage(rt: Any, family: str) -> list[dict[str, Any]]:
    """The algorithms that use a block, and which version each uses."""

    found = []
    edited = rt.blocks.get(family) is not None
    for profile in rt.presets.list_profiles():
        diagram = diagram_of(profile.get("method_config") or {})
        used = sorted(
            {
                str(node.get("block") or "")
                for node in diagram.get("nodes") or []
                if isinstance(node, dict)
                and (
                    node.get("block") == family
                    or (split_pinned(str(node.get("block") or "")) or ("",))[0] == family
                )
            }
        )
        for block_id in used:
            pinned = split_pinned(block_id)
            number = pinned[1] if pinned else (1 if edited else None)
            found.append(
                {
                    "algorithm_id": profile["profile_id"],
                    "name": profile["name"],
                    "system": bool(profile.get("system")),
                    "block_id": block_id,
                    "number": number,
                    "current": CURRENT.get(family, block_id) == block_id,
                }
            )
    return found


def _checked(payload: dict[str, Any] | str) -> tuple[BlockFile | None, list[str]]:
    try:
        file = read_file(payload)
    except ValueError as exc:
        return None, [line for line in str(exc).splitlines() if line]
    return file, check_code(file.code)


def _file_or_422(payload: dict[str, Any] | str) -> BlockFile:
    file, problems = _checked(payload)
    if file is None or problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    return file


@router.get("")
def blocks(_user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """The palette: every block with its ports, parameters and docs, by library; a site block
    by its current version."""

    sites = _site_meta(rt)
    items = [{**item, **_meta(item["block_id"], sites)} for item in catalog_items()]
    made = rt.blocks.libraries()
    return {
        "libraries": libraries(site=made),
        "blocks": items,
        "open_libraries": [*OPEN_LIBRARIES, *(item["library"] for item in made)],
    }


class LibraryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)


@router.post("/libraries")
def create_library(payload: LibraryPayload, user: AdminUser, rt: RuntimeDep) -> dict[str, Any]:
    """A library of this site's blocks (round 10): New block puts blocks in it; the Blocks page
    lists it after Link's."""

    try:
        return rt.blocks.create_library(payload.name, payload.description, user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/format")
def block_format(_user: CurrentUser) -> dict[str, Any]:
    """What a block file holds and what its code may use, for the form and the assistant."""

    from linkcraft.blocks import files

    return {
        "format": files.FORMAT,
        "description": files.__doc__,
        "libraries": list(OPEN_LIBRARIES),
        "modules": sorted(ALLOWED_MODULES),
    }


@router.get("/people")
def people(user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    """The platform's people, for a block's owner (empty when PlantCraft cannot be reached)."""

    try:
        found = rt.user_client(user).people()
    except Exception:  # noqa: BLE001 - the picker falls back to typing a user name
        return []
    return [
        {
            "username": item.get("username"),
            "name": item.get("name") or item.get("username"),
            "role": item.get("role"),
        }
        for item in found
        if item.get("username")
    ]


@router.post("/check")
def check(payload: FilePayload, _user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """Whether a block file can be saved: its contract, then its code. Nothing is saved."""

    file, problems = _checked(payload.file)
    found: dict[str, Any] = {"valid": file is not None and not problems, "problems": problems}
    if file is not None:
        found["block_id"] = file.family()
        existing = rt.blocks.get(file.block_id) if file.block_id else None
        if existing is not None:
            current = rt.blocks.file(file.block_id)
            found["contract_changed"] = (
                current is not None and current.contract() != file.contract()
            )
            found["used_by"] = len(_usage(rt, file.block_id))
    return found


@router.post("")
def create(payload: SavePayload, user: AdminUser, rt: RuntimeDep) -> dict[str, Any]:
    """A new site block from a block file (imported, written in the form or by the assistant)."""

    file = _file_or_422(payload.file)
    if file.origin == "plantcraft":
        file = file.model_copy(update={"origin": "import"})
    created = rt.blocks.create(
        file,
        user,
        version_name=payload.version_name,
        version_description=payload.version_description,
    )
    rt.audit(user, "block.created", f"block:{created['block_id']}", {"version": 1})
    return {**created, "pinned": pinned_id(created["block_id"], 1)}


@router.get("/{block_id}")
def block(
    block_id: str,
    _user: CurrentUser,
    rt: RuntimeDep,
    version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """One block as its page reads it: contract, docs, who made it, versions and where it is used.

    ``version``: the page of one of a site block's versions (the one in use when not given)."""

    resolved = _resolve(block_id)
    if resolved.startswith(f"{site_blocks.DRAFT_LIBRARY}.") or resolved not in CATALOG:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    sites = _site_meta(rt)
    meta = _meta(resolved, sites)
    in_use = meta["number"]
    if version is not None and meta["site"]:
        family = meta["family"]
        resolved = family if _is_shipped_version(family, version) else pinned_id(family, version)
        if resolved not in CATALOG:
            raise HTTPException(status_code=404, detail=t("Version not found."))
        meta = _meta(resolved, sites)
    found = CATALOG[resolved]
    item = {
        **describe_block(found.spec, t),
        "markdown": block_markdown(found.spec, t),
        **meta,
    }
    if meta["site"]:
        item["versions"] = rt.blocks.versions(meta["family"]) + _shipped_version(meta["family"])
    item["in_use"] = in_use
    item["editable"] = meta["site"] or bool(meta.get("copyable"))
    # PlantCraft's own blocks take no new version on the site (add_version refuses them).
    item["locked"] = meta["family"] in BUILTIN_IDS
    item["used_by"] = _usage(rt, meta["family"])
    return item


def _shipped_version(family: str) -> list[dict[str, Any]]:
    """Version 1 of a block Link ships that the site has edited: Link's own."""

    if family not in BUILTIN_IDS:
        return []
    return [
        {
            "block_id": family,
            "number": 1,
            "name": t("Analytics' version"),
            "description": t("The block as Analytics ships it."),
            "author": SHIPPED_AUTHOR,
            "author_name": SHIPPED_AUTHOR,
            "created_at": None,
            "shipped": True,
        }
    ]


def _is_shipped_version(family: str, version: int | None) -> bool:
    return family in BUILTIN_IDS and version == 1


@router.get("/{block_id}/code")
def code(
    block_id: str,
    _user: CurrentUser,
    rt: RuntimeDep,
    version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """The code of a block: a site block's file (any version), or the files of a shipped one."""

    resolved = _resolve(block_id)
    pinned = split_pinned(resolved)
    if pinned and _is_shipped_version(pinned[0], version):
        return {"site": False, "number": 1, "sources": shipped_sources(CATALOG[pinned[0]])}
    if pinned and rt.blocks.get(pinned[0]):
        file = rt.blocks.file(pinned[0], version or pinned[1])
        if file is None:
            raise HTTPException(status_code=404, detail=t("Version not found."))
        return {
            "site": True,
            "number": file.version.number,
            "sources": [
                {
                    "title": t("Block code"),
                    "filename": f"{pinned[0]}.py",
                    "source": file.code,
                    "line": 1,
                }
            ],
        }
    found = CATALOG.get(resolved)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    return {"site": False, "number": None, "sources": shipped_sources(found)}


@router.get("/{block_id}/image")
def image(block_id: str, _user: CurrentUser) -> Response:
    """A block's picture (round 9 M2), by the catalog id its description names (a pinned version
    has its own); its URL carries a tag of the content, so it is cached for good."""

    found = CATALOG.get(_resolve(block_id))
    if found is None or not found.spec.image:
        raise HTTPException(status_code=404, detail=t("This block has no image."))
    return image_response(found.spec.image)


@router.get("/{block_id}/file")
def block_file(
    block_id: str,
    _user: CurrentUser,
    rt: RuntimeDep,
    version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """The block file to download (a site block's version), or a shipped block's contract."""

    resolved = _resolve(block_id)
    pinned = split_pinned(resolved)
    if pinned and _is_shipped_version(pinned[0], version):
        resolved = pinned[0]
    elif pinned and rt.blocks.get(pinned[0]):
        file = rt.blocks.file(pinned[0], version or pinned[1])
        if file is None:
            raise HTTPException(status_code=404, detail=t("Version not found."))
        return file.model_dump(mode="json")
    found = CATALOG.get(resolved)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    sources = shipped_sources(found)
    note = t(
        "A block Analytics ships: its code is in {file}.",
        file=sources[0]["filename"] if sources else "Link",
    )
    return file_of_spec(found.spec, f"# {note}\n", author=SHIPPED_AUTHOR, owner=SHIPPED_AUTHOR)


@router.get("/{block_id}/copy")
def copy(
    block_id: str,
    _user: CurrentUser,
    rt: RuntimeDep,
    edit: bool = Query(default=False),
    version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """The start of a new site block from an existing one (not saved): its contract and code.

    ``edit``: the start of the next version of a block Link ships, under its own id.
    ``version``: the version of a site block to start from (the one in use when not given)."""

    resolved = _resolve(block_id)
    if not edit and rt.blocks.get(block_id) and _is_shipped_version(block_id, version):
        resolved = block_id
    if (
        edit
        and block_id in BUILTIN_IDS
        and (resolved == block_id or _is_shipped_version(block_id, version))
    ):
        if block_id.split(".")[0] not in COPYABLE:
            raise HTTPException(
                status_code=422,
                detail=t(
                    "This block reads what Analytics gives it during a run; it cannot be edited."
                ),
            )
        return edit_file(CATALOG[block_id])
    pinned = split_pinned(resolved)
    if pinned and rt.blocks.get(pinned[0]):
        file = rt.blocks.file(pinned[0], version or pinned[1])
        if file is None:
            raise HTTPException(status_code=404, detail=t("Version not found."))
        name = t("{name} (copy)", name=file.name)
        return {
            **file.model_dump(mode="json"),
            "block_id": "",
            "name": name,
            "version": {"number": 0, "name": "", "description": ""},
            "author": "",
            "owner": "",
            "origin": "user",
        }
    found = CATALOG.get(resolved)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    if resolved not in BUILTIN_IDS or found.spec.library not in COPYABLE:
        raise HTTPException(
            status_code=422,
            detail=t(
                "This block reads what Analytics gives it during a run; it cannot be copied as code."
            ),
        )
    return {**copy_file(found), "block_id": ""}


@router.post("/{block_id}/versions")
def add_version(
    block_id: str, payload: VersionPayload, user: AdminUser, rt: RuntimeDep
) -> dict[str, Any]:
    """Save a block file as the block's next version (the name and description say what changed)."""

    file = _file_or_422(payload.file)
    if block_id in BUILTIN_IDS:
        # A block PlantCraft ships changes with PlantCraft only (round 10): the page shows a lock,
        # and the server holds it too. Versions a site saved before stay as they are.
        raise HTTPException(
            status_code=409,
            detail=t(
                "A block PlantCraft ships changes with PlantCraft itself. Duplicate it to make a "
                "block of this site from it."
            ),
        )
    if rt.blocks.get(block_id) is None:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    try:
        saved = rt.blocks.add_version(
            block_id, file, user, name=payload.name, description=payload.description
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.audit(
        user,
        "block.version_saved",
        f"block:{block_id}",
        {"version": saved["number"], "name": payload.name},
    )
    return {
        **saved,
        "pinned": pinned_id(block_id, saved["number"]),
        "used_by": _usage(rt, block_id),
    }


@router.post("/{block_id}/current")
def select_version(
    block_id: str, payload: SelectPayload, user: AdminUser, rt: RuntimeDep
) -> dict[str, Any]:
    """Make one version the one in use: what the palette, new algorithms and the block's page
    take. Algorithms that already use the block keep the version they pin."""

    try:
        found = rt.blocks.select(block_id, payload.number)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    rt.audit(user, "block.version_selected", f"block:{block_id}", {"version": payload.number})
    return {"block_id": block_id, "number": payload.number, "used_by": _usage(rt, block_id)}


@router.patch("/{block_id}")
def update(block_id: str, payload: MetaPayload, user: AdminUser, rt: RuntimeDep) -> dict[str, Any]:
    """Who answers for a block, and its tags (these are not part of a version)."""

    found = rt.blocks.update(
        block_id, owner=payload.owner, owner_name=payload.owner_name, tags=payload.tags
    )
    if found is None:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    rt.audit(user, "block.updated", f"block:{block_id}", payload.model_dump(exclude_none=True))
    return found


@router.delete("/{block_id}")
def delete(block_id: str, user: AdminUser, rt: RuntimeDep) -> dict[str, Any]:
    if rt.blocks.get(block_id) is None:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    used = _usage(rt, block_id)
    if used:
        raise HTTPException(
            status_code=409,
            detail=t(
                "{count} algorithms use this block: take it out of them first.", count=len(used)
            ),
        )
    rt.blocks.delete(block_id)
    rt.folders.forget("block", block_id)
    rt.audit(user, "block.deleted", f"block:{block_id}", {})
    return {"deleted": block_id}


@router.post("/test")
@interactive
def test(payload: BlockTestPayload, user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    """Run a block on one asset's window, its inputs read from the asset's signals: nothing saved.

    A file (a draft) runs under a draft id; ``{"block_id": …}`` runs a saved block. A draft is
    code nobody saved yet, so only those who write blocks (administrators) may run one.
    """

    if isinstance(payload.file, dict) and set(payload.file) == {"block_id"}:
        # The exact block (one version, Link's own version 1 included), or a site block's in use.
        asked = str(payload.file["block_id"])
        block_id = asked if asked in CATALOG else _resolve(asked)
        found = CATALOG.get(block_id)
        if found is None:
            raise HTTPException(status_code=404, detail=t("Block not found."))
    else:
        admin(user)
        file = _file_or_422(payload.file)
        block_id = site_blocks.draft_id(file)
        site_blocks.write(block_id, file)
        found = site_blocks.code_block(file, block_id)
        CATALOG[block_id] = found
    diagram, skipped = block_diagram(
        block_id, found.spec, payload.roles, payload.signals, payload.parameters
    )
    report = compile_algorithm(diagram).report()
    if not report["valid"]:
        return {"check": report, "skipped": skipped}
    timing = payload.timing or AssetTiming()
    moment = pd.Timestamp(payload.end) if payload.end else pd.Timestamp.now(tz="UTC")
    end = window_end(moment, timing.step_seconds)
    try:
        ran = run_on_asset(
            diagram,
            payload.asset_id,
            client=rt.user_client(user),
            start=end - pd.Timedelta(seconds=timing.window_seconds),
            end=end,
            step=timing.step_seconds,
            models=rt.model_runtime(),
            algorithm_id="block-test",
            with_trace=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # PlantCraft unreachable or refusing: say so, never a 500
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    trace = ran.get("trace") or {}
    return {
        "check": report,
        "skipped": skipped,
        "asset_id": ran["asset"]["id"],
        "asset_name": ran["asset"]["name"],
        "window": (ran.get("summary") or {}).get("window"),
        "inputs": {
            key.removeprefix("in_"): value.get("value")
            for key, value in trace.items()
            if key.startswith("in_")
        },
        "outputs": trace.get("block") or {},
    }
