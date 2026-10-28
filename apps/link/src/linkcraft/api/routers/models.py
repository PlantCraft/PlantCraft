"""The process models (FMUs) Link runs: the built-in ones and those published from Models.

An admin publishes one with the FMU file itself as the request body (``application/octet-stream``,
at most ``LINKCRAFT_MAX_MODEL_MB``): it is read (never run) before it is kept, and refused with a
reason when it is not an FMU this server can use. Each published model becomes a block of the
Models library at once; ``/starter`` is a new algorithm on assets around it. ``/examples`` are the
The Simulator demo plant's model algorithms on the built-in models (PlantCraft Twin's example twins).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from linkcraft.api.deps import AdminUser, CurrentUser, EditorUser, RuntimeDep
from linkcraft.assets import examples
from linkcraft.assets.twins import model_starter
from linkcraft.blocks.convert import diagram_of
from linkcraft.blocks.models import model_block_id
from linkcraft.i18n import t
from linkcraft.models.fmu import FmuError, inspect_fmu, sha256_of

router = APIRouter()

# Where an uploaded FMU was made: a path on this host (PlantCraft Models' run page).
ORIGIN = re.compile(r"^/(?!/)[A-Za-z0-9/_.~%=&?-]{0,300}$")


class ModelText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


def _variables(info: dict[str, Any], causality: str) -> list[dict[str, Any]]:
    return [
        {key: item.get(key) for key in ("name", "unit", "description", "start")}
        for item in info.get("variables") or []
        if item.get("causality") == causality and item.get("numeric")
    ]


def model_row(model: dict[str, Any], used_by: list[dict[str, str]]) -> dict[str, Any]:
    info = model.get("info") or {}
    return {
        "model_id": model["model_id"],
        "block_id": model_block_id(model["model_id"]),
        "name": model.get("name") or model["model_id"],
        "description": model.get("description") or "",
        "builtin": bool(model.get("builtin")),
        "sha256": model.get("sha256"),
        "size": model.get("size"),
        "fmi_version": info.get("fmi_version"),
        "generation_tool": info.get("generation_tool"),
        "origin": info.get("origin"),
        "step_seconds": info.get("step_seconds"),
        "inputs": _variables(info, "input"),
        "outputs": _variables(info, "output"),
        "parameters": _variables(info, "parameter"),
        "used_by": used_by,
        "created_at": model.get("created_at"),
        "updated_at": model.get("updated_at"),
    }


def _usage(rt: Any) -> dict[str, list[dict[str, str]]]:
    """The algorithms whose diagram holds each model's block, by block id."""

    found: dict[str, list[dict[str, str]]] = {}
    for profile in rt.presets.list_profiles():
        diagram = diagram_of(profile.get("method_config") or {})
        blocks = {str(node.get("block") or "") for node in diagram.get("nodes") or []}
        for block in blocks:
            found.setdefault(block, []).append(
                {"algorithm_id": profile["profile_id"], "name": profile["name"]}
            )
    return found


@router.get("/api/models")
def models(_user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    usage = _usage(rt)
    return [
        model_row(model, usage.get(model_block_id(model["model_id"]), []))
        for model in rt.models.list()
    ]


def _examples(rt: Any, user: Any) -> list[dict[str, Any]]:
    try:
        lookup, loop_asset, area = examples.plant_lookups(rt.user_client(user))
    except Exception as exc:  # PlantCraft unreachable or refusing: say so, never a 500
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return examples.twins(lookup, area=area, loop_asset=loop_asset)


@router.get("/api/models/examples")
def model_examples(user: EditorUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    """The Simulator example model algorithms this plant can have, and which exist already."""

    return [
        {
            "algorithm_id": examples.algorithm_id(twin["name"]),
            "name": twin["name"],
            "description": twin["description"],
            "exists": rt.presets.get_profile(examples.algorithm_id(twin["name"])) is not None,
        }
        for twin in _examples(rt, user)
    ]


@router.post("/api/models/examples", status_code=201)
def create_model_examples(
    user: EditorUser,
    rt: RuntimeDep,
    name: Annotated[list[str] | None, Query(max_length=20)] = None,
) -> list[dict[str, Any]]:
    """Create the example model algorithms this plant can have (only those ``name`` lists, when
    given), each calibrated on the last hours (one the plant cannot calibrate yet is created
    without, and says why) and scheduled on the assets it was made for."""

    found = _examples(rt, user)
    if not found:
        raise HTTPException(
            status_code=404,
            detail=t(
                "The Simulator loops are not in PlantCraft: add the Simulator source and its plant map first."
            ),
        )
    created = examples.create_examples(
        rt,
        rt.user_client(user),
        rt.user_plant(user),
        owner=user.username,
        owner_name=user.name or user.username,
        names=name,
    )
    for item in created:
        rt.audit(user, "algorithm.saved", f"algorithm:{item['algorithm_id']}", {"example": True})
    return created


def _found(rt: Any, model_id: str) -> dict[str, Any]:
    found = rt.models.get(model_id)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Model not found."))
    return found


@router.get("/api/models/{model_id}")
def model(model_id: str, _user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    found = _found(rt, model_id)
    return model_row(found, _usage(rt).get(model_block_id(model_id), []))


@router.get("/api/models/{model_id}/starter")
def model_algorithm(model_id: str, _user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """A new algorithm on assets around the model, for the editor to open unsaved."""

    return model_starter(_found(rt, model_id))


@router.post("/api/models", status_code=201)
async def upload_model(
    request: Request,
    rt: RuntimeDep,
    user: AdminUser,
    name: str = "",
    description: str = "",
    origin: str = "",
) -> dict[str, Any]:
    """``origin``: the page the FMU came from (Models' "Publish to Link" sends its run page)."""

    settings = rt.settings
    if not settings.model_upload:
        raise HTTPException(403, t("Publishing models is turned off on this server."))
    if len(name) > 120 or len(description) > 2000:
        raise HTTPException(422, t("A name has at most 120 characters, a description 2,000."))
    if origin and not ORIGIN.match(origin):
        raise HTTPException(422, t("The origin is a path on this server, such as /models/runs/1."))
    limit = int(settings.max_model_mb * 1024 * 1024)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.data_dir) as folder:
        path = Path(folder) / "upload.fmu"
        size = 0
        with path.open("wb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        413, t("The file is larger than {mb} MB.", mb=f"{settings.max_model_mb:g}")
                    )
                handle.write(chunk)
        if size == 0:
            raise HTTPException(422, t("Send the FMU file as the request body."))
        try:
            info = inspect_fmu(path)
        except FmuError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not info.runs_here:
            raise HTTPException(
                422,
                t(
                    "This FMU has binaries for {platforms} only; Analytics runs on Linux 64-bit. "
                    "Export it again for Linux (OpenModelica: platforms linux64 or static).",
                    platforms=", ".join(info.platforms) or t("no platform"),
                ),
            )
        digest = sha256_of(path)
        found = rt.models.add_upload(
            path,
            info,
            digest,
            name=name.strip(),
            description=description.strip(),
            by=user.username,
            origin=origin,
        )
    rt.refresh_models()
    rt.audit(user, "model.published", f"model:{found['model_id']}", {"sha256": digest})
    return model_row(found, [])


@router.patch("/api/models/{model_id}")
def rename_model(
    model_id: str, body: ModelText, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    _found(rt, model_id)
    found = rt.models.update(model_id, name=body.name.strip(), description=body.description.strip())
    rt.refresh_models()
    rt.audit(user, "model.changed", f"model:{model_id}", {"name": body.name})
    return model_row(found or {}, _usage(rt).get(model_block_id(model_id), []))


@router.delete("/api/models/{model_id}", status_code=204)
def delete_model(model_id: str, rt: RuntimeDep, user: AdminUser) -> None:
    found = _found(rt, model_id)
    if found["builtin"]:
        raise HTTPException(409, t("Built-in models come with Analytics and stay."))
    used = _usage(rt).get(model_block_id(model_id), [])
    if used:
        raise HTTPException(
            409,
            t(
                "Algorithms use this model: {names}. Change or delete them first.",
                names=", ".join(item["name"] for item in used),
            ),
        )
    rt.models.delete(model_id)
    rt.refresh_models()
    rt.audit(user, "model.deleted", f"model:{model_id}", {"sha256": found["sha256"]})
