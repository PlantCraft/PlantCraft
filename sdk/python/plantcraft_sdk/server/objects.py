"""An app's objects and examples for notebooks: one format for every app.

A notebook reads an app's objects with ``pc.app("link").list("block")`` and runs one with
``.run(...)`` (``plantcraft_notebook``). PlantCraft forwards those reads to the app with the
person's identity (``GET /api/v1/apps/<app>/objects/<kind>``), so the app answers them with the
same access checks as its pages. The app declares each kind in ``[[contributes.objects]]`` and
serves it with ``AppObjects``::

    objects = AppObjects()

    @objects.lister("block")
    def blocks(user, rt):
        return [object_item(b["block_id"], b["name"], description=b["summary"]) for b in ...]

    @objects.getter("block")
    def block(user, rt, block_id):
        return {...}  # or None: 404

    api = suite_api(..., routers=[..., objects.router(), notebooks_router(EXAMPLES, MANIFEST)])

``<prefix>api/objects/<kind>`` answers ``{"format": "plantcraft-objects/1", "kind", "items"}``
(each item an ``id``, a ``name`` and the fields the app adds) and ``<prefix>api/objects/<kind>/<id>``
the object itself, with its ``id`` and ``name``. A kind that runs in the app (``run = "app"``,
a simulation) also takes ``POST <prefix>api/objects/<kind>/run`` (``@objects.runner``).

``notebooks_router`` serves the app's examples (``[contributes.notebooks] examples``) and, for
objects that run on the person's computer, its runtime: the packages named in
``[contributes.notebooks] runtime`` as they are installed in the app, in one zip. The notebook
library unpacks it on the person's computer (or in their browser) and calls
``<entry>.run(kind, item, plant, app, **options)``: nothing a notebook runs runs on the server.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from plantcraft_sdk.i18n import t
from plantcraft_sdk.notebooks import FORMAT as NOTEBOOKS_FORMAT
from plantcraft_sdk.notebooks import Example
from plantcraft_sdk.server.access import CurrentUser, runtime

FORMAT = "plantcraft-objects/1"
RUNTIME_FORMAT = "plantcraft-runtime/1"
# A runtime is code: a few MB. Past this something else was packed (data, a model folder).
MAX_RUNTIME_BYTES = 40 * 1024 * 1024
SKIPPED = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
# A fixed time for every file of the zip: the same code gives the same zip and the same digest.
STAMP = (2020, 1, 1, 0, 0, 0)

Lister = Callable[[Any, Any], list[dict[str, Any]]]
Getter = Callable[[Any, Any, str], dict[str, Any] | None]
Runner = Callable[[Any, Any, str, dict[str, Any]], dict[str, Any]]
# What a notebook may ask an app to run with (a simulation's stop time, its parameters).
MAX_OPTIONS = 100


class RunRequest(BaseModel):
    """A notebook asks the app to run one object (``run = "app"``): its id and the options."""

    id: str = Field(min_length=1, max_length=400)
    options: dict[str, Any] = Field(default_factory=dict, max_length=MAX_OPTIONS)


def object_item(object_id: str, name: str, **fields: Any) -> dict[str, Any]:
    """One item of a list: its ``id``, its ``name`` and the fields the app adds (JSON values;
    ``None`` ones are left out)."""

    return {
        "id": str(object_id),
        "name": str(name or object_id),
        **{key: value for key, value in fields.items() if value is not None},
    }


def objects_answer(kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"format": FORMAT, "kind": kind, "items": list(items)}


class AppObjects:
    """The kinds of object an app serves to notebooks, each with its list and its get."""

    def __init__(self) -> None:
        self.listers: dict[str, Lister] = {}
        self.getters: dict[str, Getter] = {}
        self.runners: dict[str, Runner] = {}

    def lister(self, kind: str) -> Callable[[Lister], Lister]:
        def register(function: Lister) -> Lister:
            self.listers[kind] = function
            return function

        return register

    def getter(self, kind: str) -> Callable[[Getter], Getter]:
        def register(function: Getter) -> Getter:
            self.getters[kind] = function
            return function

        return register

    def runner(self, kind: str) -> Callable[[Runner], Runner]:
        """For a kind that runs in the app (``run = "app"``): start one run of an object and
        answer what the notebook reads back, ``{"kind": "run", "id": ...}`` (an object of a kind
        the app also serves). The app checks who may run and its own switches."""

        def register(function: Runner) -> Runner:
            self.runners[kind] = function
            return function

        return register

    def kinds(self) -> list[str]:
        return sorted(set(self.listers) | set(self.getters))

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/objects", tags=["objects"])

        @router.get("/{kind}")
        def listing(kind: str, user: CurrentUser, request: Request) -> dict[str, Any]:
            """The objects of one kind the person may read (``plantcraft-objects/1``)."""

            lister = self.listers.get(kind)
            if lister is None:
                raise HTTPException(status_code=404, detail=t("No objects of this kind."))
            return objects_answer(kind, lister(user, runtime(request)))

        @router.post("/{kind}/run", status_code=201)
        def start(
            kind: str, body: RunRequest, user: CurrentUser, request: Request
        ) -> dict[str, Any]:
            """Run one object in the app (a simulation in its queue); what to read back."""

            runner = self.runners.get(kind)
            if runner is None:
                raise HTTPException(
                    status_code=404, detail=t("Objects of this kind do not run here.")
                )
            started = runner(user, runtime(request), body.id, dict(body.options))
            if not started.get("kind") or not started.get("id"):
                raise HTTPException(status_code=500, detail="a runner answers a kind and an id")
            return {"format": FORMAT, "kind": kind, "id": body.id, "started": started}

        @router.get("/{kind}/{object_id:path}")
        def one(kind: str, object_id: str, user: CurrentUser, request: Request) -> dict[str, Any]:
            """One object, whole: what a notebook needs to read it or run it."""

            getter = self.getters.get(kind)
            found = getter(user, runtime(request), object_id) if getter else None
            if found is None:
                raise HTTPException(status_code=404, detail=t("Not found."))
            return {"id": object_id, **found, "kind": kind}

        return router


def _package_folder(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        raise LookupError(f"runtime package {name!r} is not installed here")
    return Path(next(iter(spec.submodule_search_locations)))


@cache
def runtime_zip(packages: tuple[str, ...], app: str, version: str, entry: str) -> bytes:
    """``packages`` as installed here, in one zip with ``plantcraft-runtime.json``: the same
    files give the same bytes."""

    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "format": RUNTIME_FORMAT,
            "app": app,
            "version": version,
            "packages": list(packages),
            "entry": entry,
        }
        info = zipfile.ZipInfo("plantcraft-runtime.json", STAMP)
        archive.writestr(info, json.dumps(manifest, indent=2))
        for name in packages:
            folder = _package_folder(name)
            for path in sorted(folder.rglob("*")):
                relative = path.relative_to(folder.parent)
                if not path.is_file() or SKIPPED & set(relative.parts) or path.suffix == ".pyc":
                    continue
                total += path.stat().st_size
                if total > MAX_RUNTIME_BYTES:
                    raise ValueError(f"the runtime is over {MAX_RUNTIME_BYTES} bytes")
                info = zipfile.ZipInfo(relative.as_posix(), STAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def notebooks_router(examples: list[Example], manifest: Any) -> APIRouter:
    """``<prefix>api/notebooks/examples[/<id>]`` and ``<prefix>api/notebooks/runtime`` from the
    app's parsed ``AppManifest`` (``[contributes.notebooks]``; None: no runtime)."""

    router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])
    table = manifest.contributes.notebooks if manifest is not None else None
    by_id = {item.id: item for item in examples}

    @router.get("/examples")
    def example_list(_user: CurrentUser) -> dict[str, Any]:
        """The app's examples, for ``Examples/<app>`` in Notebooks."""

        return {"format": NOTEBOOKS_FORMAT, "items": [item.item() for item in examples]}

    @router.get("/examples/{example_id}")
    def example(example_id: str, _user: CurrentUser) -> dict[str, Any]:
        found = by_id.get(example_id)
        if found is None:
            raise HTTPException(status_code=404, detail=t("Not found."))
        return found.notebook()

    @router.get("/runtime")
    def runtime_file(request: Request, _user: CurrentUser) -> Response:
        """What runs the app's objects on the person's computer, in one zip."""

        if table is None or not table.runtime or not table.entry:
            raise HTTPException(status_code=404, detail=t("This app runs nothing locally."))
        body = runtime_zip(tuple(table.runtime), manifest.app.id, manifest.app.version, table.entry)
        digest = hashlib.sha256(body).hexdigest()
        if request.headers.get("if-none-match") == f'"{digest}"':
            return Response(status_code=304, headers={"ETag": f'"{digest}"'})
        return Response(
            body,
            media_type="application/zip",
            headers={
                "ETag": f'"{digest}"',
                "X-Runtime-Sha256": digest,
                "Content-Disposition": f'attachment; filename="{manifest.app.id}-runtime.zip"',
            },
        )

    return router


__all__ = [
    "AppObjects",
    "FORMAT",
    "RUNTIME_FORMAT",
    "RunRequest",
    "notebooks_router",
    "object_item",
    "objects_answer",
    "runtime_zip",
]
