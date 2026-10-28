"""HTTP routes: Notebooks (``processcraft/notebooks``, docs/en/notebooks.md).

``/api/notebooks`` is the page's own API: the switch (administrators), the notebooks PlantCraft
wrote for the person, and "Open in a notebook" (a new one from signals, an asset or nothing).

``/notebooks/lite/`` serves JupyterLite, built into the image (``notebooks/build.py``), to people
who may read the plant (viewers and up) while the switch is on, and 404 otherwise. Its file
browser reads the person's ``PlantCraft`` folder from here: ``api/contents/.../all.json`` lists
it and ``files/PlantCraft/<name>`` is a notebook, the paths JupyterLite reads a static site's
files from.

``/api/notebooks/kits/<id>.zip`` sends the Notebooks kit for a person's own computer, with this
server's address added (``notebooks.kits``), when an administrator turned its download on, and
``POST /api/notebooks/token`` creates the token the kit reads with (90 days, at most the
administrator's limit for tokens).
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from processcraft.api import notebook_examples as examples
from processcraft.api.deps import AdminUser, CurrentUser, Runtime, open_to
from processcraft.auth.usage import CONCURRENT_RANGE, PER_MINUTE_RANGE
from processcraft.db import utc_text
from processcraft.i18n import t
from processcraft.notebooks import EXAMPLES_FOLDER, FOLDER, OLD_FOLDER, kits, templates
from processcraft.notebooks.dist import build_info, is_fresh

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LITE = "/notebooks/lite/"
# Answers JupyterLite reads again on every visit: never from a cache.
FRESH = {"Cache-Control": "no-store"}
# A file of the current build, under its own path: kept by the browser for a year.
KEPT = {"Cache-Control": "private, max-age=31536000, immutable"}
# Pyodide's files, which some systems' MIME tables do not know (a module worker needs its type).
for _type, _suffix in (("application/wasm", ".wasm"), ("text/javascript", ".mjs")):
    mimetypes.add_type(_type, _suffix)


def lite_dist() -> Path:
    configured = os.environ.get("PLANTCRAFT_NOTEBOOKS_DIST", "").strip()
    return Path(configured) if configured else PROJECT_ROOT / "notebooks" / "dist"


def package_wheel() -> Path | None:
    """The ``plantcraft-notebook`` wheel the build put beside JupyterLite's own packages."""

    found = sorted((lite_dist() / "pypi").glob("plantcraft_notebook-*.whl"))
    return found[-1] if found else None


class SettingsPayload(BaseModel):
    """What changes: the switch, the kits' download, or both."""

    enabled: bool | None = None
    kit_enabled: bool | None = None


class LimitsPayload(BaseModel):
    per_minute: int = Field(ge=PER_MINUTE_RANGE[0], le=PER_MINUTE_RANGE[1])
    concurrent: int = Field(ge=CONCURRENT_RANGE[0], le=CONCURRENT_RANGE[1])


class CreatePayload(BaseModel):
    kind: Literal["series", "asset", "blank", "example"] = "blank"
    example: str = Field(default="", max_length=60)
    signals: list[str] = Field(default_factory=list, max_length=200)
    start: str = Field(default="-24h", max_length=40)
    end: str = Field(default="now", max_length=40)
    step: int | None = Field(default=None, ge=1, le=86_400 * 31)
    asset_id: str = Field(default="", max_length=200)
    name: str = Field(default="", max_length=200)
    # Where the person came from, said in the first cell ("the Historian export").
    origin: str = Field(default="", max_length=80)


def _audit(rt: Any, actor: str, action: str, subject: str, detail: dict[str, Any]) -> None:
    rt.workspace.audit.record(actor, action, subject, detail, app_id="processcraft")


def lite_base() -> str:
    """Where JupyterLite is served: under its build, cached for a year (``notebooks.dist``)."""

    info = build_info(lite_dist())
    return f"{LITE}v/{info['build']}/" if info else LITE


def lab_url(path: str = "") -> str:
    return f"{lite_base()}lab/index.html" + (f"?path={quote(path)}" if path else "")


@router.get("/api/notebooks")
def overview(user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """The switch, whether this image holds JupyterLite, the package, and the person's notebooks."""

    store = rt.workspace.notebooks
    wheel = package_wheel()
    info = build_info(lite_dist())
    return {
        **store.settings(),
        "built": (lite_dist() / "lab" / "index.html").is_file(),
        "lab_url": lab_url(),
        # What "Install Python in this browser" downloads once (the list: /api/notebooks/files).
        "browser": {"build": info["build"], "bytes": info["bytes"], "files": len(info["files"])}
        if info
        else None,
        "package": {"file": wheel.name, "url": f"{LITE}pypi/{wheel.name}"} if wheel else None,
        "notebooks": [{**item, "url": lab_url(item["path"])} for item in store.list(user)],
        "examples": examples.listing(rt, user),
        "limits": rt.workspace.usage.settings(),
        "kits": _kits(
            store.settings(), rt.workspace.assistant_access.longest_days(kits.KIT_TOKEN_DAYS)
        ),
    }


def _kits(settings: dict[str, Any], token_days: int) -> dict[str, Any] | None:
    """The kits this installation has (the bundle's optional part) and whether people may
    download them; None when it has none."""

    found = kits.catalog()
    if found is None:
        return None
    return {
        "enabled": settings["kit_enabled"],
        "version": found["version"],
        "token_days": token_days,
        "kits": [
            {
                "id": item["id"],
                "system": item.get("system", ""),
                "arch": item.get("arch", ""),
                "bytes": item.get("bytes", 0),
                "sha256": item.get("sha256", ""),
                "url": f"/api/notebooks/kits/{item['id']}.zip",
                "installer": {
                    "url": f"/api/notebooks/kits/{item['id']}/installer",
                    "file": item["installer"]["file"],
                    "bytes": item["installer"].get("bytes", 0),
                    "sha256": item["installer"].get("sha256", ""),
                }
                if item.get("installer")
                else None,
            }
            for item in found["kits"]
        ],
    }


def _origin(request: Request) -> str:
    """This server as the person's browser reached it."""

    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    return f"{scheme}://{host}"


@router.get("/api/notebooks/kits/{kit_id}.zip")
@open_to("viewer")
def kit_download(kit_id: str, user: CurrentUser, rt: Runtime, request: Request) -> Any:
    """The kit for one system, with this server's address (and local CA) added."""

    settings = rt.workspace.notebooks.settings()
    if not (settings["enabled"] and settings["kit_enabled"]):
        raise HTTPException(status_code=404, detail=t("Not found."))
    found = kits.kit_path(kit_id)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Not found."))
    path, item = found
    listing = kits.catalog() or {}
    try:
        length, body = kits.personalized(
            path, kits.kit_files(_origin(request), str(listing.get("version") or ""))
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=t("This kit cannot be sent.")) from exc
    _audit(rt, user, "notebooks.kit_download", f"kit:{kit_id}", {"version": listing.get("version")})
    return StreamingResponse(
        body,
        media_type="application/zip",
        headers={
            "Content-Length": str(length),
            "Content-Disposition": f'attachment; filename="{item["file"]}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/notebooks/kits/{kit_id}/installer")
@open_to("viewer")
def kit_installer(kit_id: str, user: CurrentUser, rt: Runtime) -> Any:
    """The Windows setup or the macOS app of a kit, as it was built: the server and the token
    reach it later, through "Connect this computer"."""

    settings = rt.workspace.notebooks.settings()
    if not (settings["enabled"] and settings["kit_enabled"]):
        raise HTTPException(status_code=404, detail=t("Not found."))
    found = kits.kit_path(kit_id, installer=True)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Not found."))
    path, item = found
    listing = kits.catalog() or {}
    _audit(
        rt,
        user,
        "notebooks.kit_download",
        f"kit:{kit_id}",
        {"version": listing.get("version"), "installer": True},
    )
    media = (
        "application/vnd.microsoft.portable-executable"
        if path.suffix == ".exe"
        else "application/zip"
    )
    return FileResponse(
        path,
        media_type=media,
        filename=item["file"],
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/notebooks/token", status_code=201)
@open_to("viewer")
def kit_token(user: CurrentUser, rt: Runtime, request: Request) -> dict[str, Any]:
    """A token for the person's kit: read-only, their own access, 90 days (at most the
    administrator's limit); shown once, with the connection code that carries it."""

    if not rt.workspace.notebooks.enabled():
        raise HTTPException(
            status_code=409, detail=t("An administrator has to turn notebooks on first.")
        )
    store = rt.workspace.assistant_access
    label = t("Notebooks kit, {date}", date=utc_text()[:10])
    try:
        record, token = store.create(user, label=label, longest=kits.KIT_TOKEN_DAYS)
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail=t("Revoke a token first: at most 10 can be active.")
        ) from exc
    detail = {"token_id": record["token_id"], "label": label, "expires_at": record["expires_at"]}
    _audit(rt, user, "assistant_token.create", f"user:{user}", detail)
    code = kits.connection_code(_origin(request), token, kits.local_ca())
    return {**record, "token": token, "code": code}


# The link the person's computer answers (the Notebooks app registers it when installed).
SCHEME = "plantcraft-notebooks"


@router.post("/api/notebooks/pair", status_code=201)
@open_to("viewer")
def pair(user: CurrentUser, rt: Runtime, request: Request) -> dict[str, Any]:
    """ "Connect this computer": a link that hands the Notebooks app on this computer a one-time
    code (``PAIR_SECONDS``), which it trades for the kit's token (``notebooks_pair``). Nobody
    copies a token; the local certificate authority comes with its SHA-256 to check it by."""

    store = rt.workspace.notebooks
    settings = store.settings()
    if not (settings["enabled"] and settings["kit_enabled"]):
        raise HTTPException(
            status_code=409, detail=t("An administrator has to turn notebooks on first.")
        )
    code, expires = store.pairing_code(user)
    ca = kits.local_ca()
    query = {"server": _origin(request), "code": code}
    if ca:
        query["ca"] = hashlib.sha256(ca).hexdigest()
    return {"link": f"{SCHEME}://connect?{urlencode(query)}", "expires_at": expires}


@router.get("/api/notebooks/files")
def browser_files(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Every file the browser keeps, for the page to fetch once into its cache."""

    info = build_info(lite_dist()) if rt.workspace.notebooks.enabled() else None
    if info is None:
        raise HTTPException(status_code=404, detail=t("Not found."))
    base = lite_base()
    return {**info, "files": [base + quote(path) for path in info["files"]]}


@router.put("/api/notebooks/settings")
def save_settings(payload: SettingsPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    store = rt.workspace.notebooks
    if payload.enabled and not store.settings()["allowed"]:
        raise HTTPException(
            status_code=409,
            detail=t("This installation turned notebooks off (PLANTCRAFT_NOTEBOOKS=off)."),
        )
    saved = store.save_settings(
        enabled=payload.enabled, kit_enabled=payload.kit_enabled, actor=admin
    )
    detail = {"enabled": saved["enabled"], "kit_enabled": saved["kit_enabled"]}
    _audit(rt, admin, "notebooks.settings", "setting:notebooks", detail)
    return saved


@router.put("/api/notebooks/limits")
def save_limits(
    payload: LimitsPayload, admin: AdminUser, rt: Runtime, request: Request
) -> dict[str, Any]:
    """How much one person may ask API v1 for (``processcraft.api.usage``): this process at once,
    the others within seconds."""

    saved = rt.workspace.usage.save_settings(
        per_minute=payload.per_minute, concurrent=payload.concurrent, actor=admin
    )
    limits = getattr(request.app.state, "usage_limits", None)
    if limits is not None:
        limits.forget()
    detail = {"per_minute": saved["per_minute"], "concurrent": saved["concurrent"]}
    _audit(rt, admin, "notebooks.limits", "setting:usage-limits", detail)
    return saved


@router.post("/api/notebooks", status_code=201)
@open_to("viewer")
def create(payload: CreatePayload, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A new notebook in the person's folder whose first cells load what they were looking at."""

    store = rt.workspace.notebooks
    if not store.enabled():
        raise HTTPException(
            status_code=409, detail=t("An administrator has to turn notebooks on first.")
        )
    signals = [value.strip() for value in payload.signals if value.strip()]
    if payload.kind == "series":
        if not signals:
            raise HTTPException(status_code=422, detail=t("Pick at least one signal."))
        title, notebook = templates.series_notebook(
            signals, payload.start, payload.end, step=payload.step, origin=payload.origin
        )
    elif payload.kind == "asset":
        if not payload.asset_id.strip():
            raise HTTPException(status_code=422, detail=t("Pick an asset."))
        title, notebook = templates.asset_notebook(payload.asset_id.strip(), payload.name)
    elif payload.kind == "example":
        # An example opens from the Examples folder: never a copy in My notebooks (owner,
        # 2026-10-26: the copies showed "Read a signal and plot it" three times).
        item = examples.find(rt, user, payload.example)
        notebook = examples.notebook(rt, user, item) if item else None
        if item is None or notebook is None:
            raise HTTPException(status_code=422, detail=t("Pick one of the examples."))
        name, path = item["name"], item["path"]
        size = len(json.dumps(notebook).encode("utf-8"))
        return {
            "notebook_id": "",
            "name": name,
            "path": path,
            "created_at": utc_text(),
            "size": size,
            "url": lab_url(path),
        }
    else:
        title, notebook = templates.blank_notebook()
    saved = store.create(user, payload.name or title, notebook)
    _audit(
        rt,
        user,
        "notebooks.create",
        f"notebook:{saved['notebook_id']}",
        {"name": saved["name"], "kind": payload.kind, "signals": signals[:20]}
        | ({"example": payload.example} if payload.kind == "example" else {}),
    )
    return {**saved, "url": lab_url(saved["path"])}


@router.delete("/api/notebooks/{notebook_id}")
@open_to("viewer")
def delete(notebook_id: str, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    if not rt.workspace.notebooks.delete(user, notebook_id):
        raise HTTPException(status_code=404, detail=t("Not found."))
    return {"deleted": notebook_id}


# JupyterLite ----------------------------------------------------------------------------


def _model(name: str, path: str, kind: str, created: str, size: int | None) -> dict[str, Any]:
    return {
        "name": name,
        "path": path,
        "type": kind,
        "format": None if kind == "directory" else "json",
        "mimetype": None if kind == "directory" else "application/x-ipynb+json",
        "content": None,
        "created": created,
        "last_modified": created,
        "size": size,
        "writable": True,
        "hash": None,
        "hash_algorithm": None,
    }


def _listing(path: str, content: list[dict[str, Any]], modified: str) -> JSONResponse:
    directory = _model(path.rsplit("/", 1)[-1], path, "directory", modified, None)
    return JSONResponse({**directory, "format": "json", "content": content}, headers=FRESH)


def _contents(rt: Any, user: str, path: str) -> JSONResponse:
    """``api/contents/<path>/all.json``: the examples, one folder per app, and the person's folder."""

    items = rt.workspace.notebooks.list(user) if path in ("", FOLDER) else []
    # A folder is as new as its newest notebook (an empty one: now), never 1970.
    newest = max((item["created_at"] for item in items), default=utc_text())
    if path == "":
        folders = [
            _model(EXAMPLES_FOLDER, EXAMPLES_FOLDER, "directory", newest, None),
            _model(FOLDER, FOLDER, "directory", newest, None),
        ]
        return _listing("", folders, newest)
    if path == EXAMPLES_FOLDER:
        found = examples.folders(examples.listing(rt, user))
        content = [
            _model(name, f"{EXAMPLES_FOLDER}/{name}", "directory", newest, None) for name in found
        ]
        return _listing(EXAMPLES_FOLDER, content, newest)
    if path.startswith(f"{EXAMPLES_FOLDER}/"):
        content = [
            _model(item["name"], item["path"], "notebook", newest, None)
            for item in examples.listing(rt, user)
            if f"{EXAMPLES_FOLDER}/{item['folder']}" == path
        ]
        return _listing(path, content, newest)
    if path == FOLDER:
        return _listing(
            FOLDER,
            [
                _model(item["name"], item["path"], "notebook", item["created_at"], item["size"])
                for item in items
            ],
            newest,
        )
    return _listing(path, [], newest)


def _file(rt: Any, user: str, path: str) -> JSONResponse | None:
    """``files/<folder>/<name>``: an example or one of the person's notebooks."""

    path = path[len("files/") :]
    folder, _, name = path.partition("/")
    if folder == EXAMPLES_FOLDER:
        item = examples.find(rt, user, path)
        found = examples.notebook(rt, user, item) if item else None
        return JSONResponse(found, headers=FRESH) if found is not None else None
    if folder in (FOLDER, OLD_FOLDER):
        mine = rt.workspace.notebooks.get(user, name, content=True)
        return JSONResponse(mine["content"], headers=FRESH) if mine is not None else None
    return None


@router.get(LITE + "{path:path}", include_in_schema=False)
def lite(path: str, user: CurrentUser, rt: Runtime) -> Any:
    if not rt.workspace.notebooks.enabled():
        raise HTTPException(status_code=404, detail=t("Not found."))
    root = lite_dist().resolve()
    # ``v/<build>/...``: the files of one build. The current build's are kept by the browser;
    # another build's (a page left open across an update) are served, never kept.
    kept = False
    if path.startswith("v/"):
        build, _, path = path[2:].partition("/")
        info = build_info(root)
        kept = info is not None and build == info["build"]
    if path.startswith("api/contents/") and path.endswith("all.json"):
        folder = path[len("api/contents/") : -len("all.json")].strip("/")
        return _contents(rt, user, folder)
    if path.startswith("files/"):
        found = _file(rt, user, path)
        if found is None:
            raise HTTPException(status_code=404, detail=t("Not found."))
        return found
    if path == "" or path.endswith("/"):
        path += "index.html"
    candidate = (root / path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail=t("Not found."))
    if is_fresh(candidate):
        return FileResponse(candidate, headers=FRESH)
    return FileResponse(candidate, headers=KEPT if kept else None)
