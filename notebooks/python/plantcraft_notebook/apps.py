"""The apps' objects in a notebook: one format for every app (owner, 2026-10-26).

Each app of the suite says what it offers notebooks (``[[contributes.objects]]`` in its
``app.toml``) and PlantCraft lists it at ``/api/v1/objects``; this module builds everything from
that list, nothing written here per app::

    import plantcraft_notebook as pc
    pc.apps()                                   # what each app offers
    link = pc.app("link")
    link.blocks()                               # the same as link.list("block"): a table
    block = link.get("block", "stats.mean")     # the object, with its description and ports
    block.run(asset="FIC-101", start="-24h")    # runs on your computer (or in this browser)
    pc.app("models").get("model", "tank/Tank").run(stop=600).wait()  # in Models' queue (if allowed)

An object whose kind runs locally (``run = "local"``: Link's blocks and algorithms) runs here
with the app's own code: PlantCraft hands over the app's runtime (its Python packages, in one zip)
the first time, and the app's ``run(kind, item, plant, app, **options)`` reads the data it needs
through PlantCraft with your access. Nothing runs on the server, and nothing is written there.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd

RUNTIME_FILE = "plantcraft-runtime.json"
# A run read back from its app is not finished while it says so.
WAITING = {"queued", "running", "pending", "starting"}
_RUNTIMES: dict[str, Any] = {}


def _pc() -> Any:
    return sys.modules["plantcraft_notebook"]


def _offers() -> list[dict[str, Any]]:
    return list(_pc().client().get("/api/v1/objects").get("apps") or [])


def _names(offer: dict[str, Any]) -> set[str]:
    """What a person may call an app: its id, its name, its short name and its address."""

    name = str(offer.get("name") or "")
    prefix = str(offer.get("prefix") or "").strip("/")
    found = {offer["app"], name, name.removeprefix("PlantCraft ").strip(), prefix}
    return {item.casefold() for item in found if item}


def apps() -> pd.DataFrame:
    """The apps that offer notebooks something: their kinds of object, examples and whether
    their objects run on your computer."""

    rows = [
        {
            "app": offer["app"],
            "name": offer.get("name"),
            "kinds": ", ".join(kind["kind"] for kind in offer.get("kinds") or []),
            "examples": bool(offer.get("examples")),
            "runs here": bool(offer.get("runtime")),
        }
        for offer in _offers()
    ]
    frame = pd.DataFrame(rows, columns=["app", "name", "kinds", "examples", "runs here"])
    return frame.set_index("app")


def app(name: str) -> App:
    """One app by its id (``linkcraft``), its name (``PlantCraft Analytics``, ``Link``) or its address
    (``link``)."""

    wanted = str(name).strip().strip("/").casefold()
    offers = _offers()
    for offer in offers:
        if wanted in _names(offer):
            return App(offer)
    known = ", ".join(sorted(str(item.get("name") or item["app"]) for item in offers)) or "none"
    raise _pc().PlantCraftError(404, f"no app {name!r} offers notebooks objects here ({known})")


class App:
    """An app as a notebook sees it: its kinds of object, listed and read the same way for all."""

    def __init__(self, offer: dict[str, Any]):
        self.id = str(offer["app"])
        self.name = str(offer.get("name") or self.id)
        self.version = str(offer.get("version") or "")
        self.offer = offer
        self.kind_specs = {item["kind"]: item for item in offer.get("kinds") or []}

    def __repr__(self) -> str:
        kinds = ", ".join(self.kind_specs) or "no objects"
        return f"<{self.name} {self.version}: {kinds}>"

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | {f"{kind}s" for kind in self.kind_specs})

    def __getattr__(self, name: str) -> Any:
        # link.blocks() is link.list("block"): the shortcuts come from the app's own kinds.
        kinds = self.__dict__.get("kind_specs") or {}
        if name.endswith("s") and name[:-1] in kinds:
            return lambda: self.list(name[:-1])
        raise AttributeError(name)

    def kinds(self) -> pd.DataFrame:
        """The kinds of object this app offers, and where each runs."""

        rows = [
            {
                "kind": kind,
                "title": spec.get("title"),
                "runs": {"local": "here", "app": f"in {self.name}"}.get(spec.get("run"), "no"),
                "description": spec.get("description"),
            }
            for kind, spec in self.kind_specs.items()
        ]
        return pd.DataFrame(rows, columns=["kind", "title", "runs", "description"]).set_index(
            "kind"
        )

    def _kind(self, kind: str) -> dict[str, Any]:
        if kind not in self.kind_specs:
            known = ", ".join(self.kind_specs) or "none"
            raise _pc().PlantCraftError(404, f"{self.name} has no {kind!r} objects ({known})")
        return self.kind_specs[kind]

    def _path(self, kind: str, object_id: str | None = None) -> str:
        pc = _pc()
        path = f"/api/v1/apps/{pc._quote(self.id)}/objects/{pc._quote(kind)}"
        return path if object_id is None else f"{path}/{pc._quote(str(object_id))}"

    def list(self, kind: str) -> pd.DataFrame:
        """The objects of ``kind`` you may read, one row each, by id."""

        self._kind(kind)
        items = _pc().client().get(self._path(kind)).get("items") or []
        frame = pd.DataFrame(items)
        return frame.set_index("id") if "id" in frame.columns else frame

    def get(self, kind: str, object_id: str) -> AppObject:
        """One object, whole: what the app says about it, and ``.run(...)`` when it runs."""

        self._kind(kind)
        return AppObject(self, kind, _pc().client().get(self._path(kind, object_id)))

    def runtime(self) -> Any:
        """The app's module that runs its objects here (downloaded once per session)."""

        if not self.offer.get("runtime"):
            raise _pc().PlantCraftError(404, f"{self.name} runs nothing on your computer")
        if self.id not in _RUNTIMES:
            _RUNTIMES[self.id] = load_runtime(self.id)
        return _RUNTIMES[self.id]


class AppObject(dict):
    """An app's object: a dict of what the app says about it, with ``app`` and ``kind``."""

    def __init__(self, owner: App, kind: str, data: dict[str, Any]):
        super().__init__(data)
        self.app = owner
        self.kind = kind

    def __repr__(self) -> str:
        return f"<{self.app.name} {self.kind} {self.get('id')}: {self.get('name')}>"

    def run(self, **options: Any) -> Any:
        """Run the object. Link's blocks and algorithms run here, on data read with your access
        (``help(obj.app.runtime().run)`` lists the options). A model runs in its app's queue, when
        the app's administrator allows runs from notebooks: you get the run back, ``.wait()``
        for it to finish."""

        where = self.app._kind(self.kind).get("run")
        if where == "local":
            return self.app.runtime().run(self.kind, dict(self), _pc(), self.app, **options)
        if where == "app":
            body = {"id": str(self.get("id")), "options": options}
            answer = _pc().client().request("POST", self.app._path(self.kind) + "/run", body)
            started = answer["started"]
            return self.app.get(started["kind"], started["id"])
        raise _pc().PlantCraftError(
            400, f"{self.app.name} {self.kind}s do not run from a notebook ({where or 'none'})"
        )

    def refresh(self) -> AppObject:
        """The object read again from its app."""

        return self.app.get(self.kind, str(self.get("id")))

    def wait(self, timeout: float = 600.0, every: float = 2.0) -> AppObject:
        """Read the object again until it is no longer queued or running (a run of a model)."""

        current: AppObject = self
        deadline = time.monotonic() + timeout
        while str(current.get("status") or "") in WAITING:
            if time.monotonic() > deadline:
                raise TimeoutError(f"{current!r} still {current.get('status')} after {timeout} s")
            time.sleep(every)
            current = current.refresh()
        return current


# The runtime ---------------------------------------------------------------------------------


def _cache_folder() -> Path:
    if _pc().IN_BROWSER:
        return Path(tempfile.gettempdir()) / "plantcraft-runtimes"
    configured = os.environ.get("PLANTCRAFT_RUNTIME_DIR", "").strip()
    if configured:
        return Path(configured)
    from plantcraft_notebook.kit import app_folder

    return app_folder() / "runtimes"


def _unpack(data: bytes, folder: Path) -> None:
    """The zip into ``folder``, every name checked: no absolute path, no ``..``."""

    scratch = folder.with_name(folder.name + ".part")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or ":" in name:
                raise ValueError(f"unsafe name in the runtime: {name!r}")
        archive.extractall(scratch)
    if folder.exists():
        return
    scratch.replace(folder)


def load_runtime(app_id: str) -> Any:
    """Download ``app_id``'s runtime (or reuse the copy of the same digest), add it to
    ``sys.path`` and import its entry."""

    pc = _pc()
    data = pc.client().download(f"/api/v1/apps/{pc._quote(app_id)}/notebooks/runtime")
    digest = hashlib.sha256(data).hexdigest()
    folder = _cache_folder() / f"{app_id}-{digest[:16]}"
    if not (folder / RUNTIME_FILE).is_file():
        folder.parent.mkdir(parents=True, exist_ok=True)
        _unpack(data, folder)
    manifest = json.loads((folder / RUNTIME_FILE).read_text(encoding="utf-8"))
    # A package another app's runtime brought already (the SDK every app shares) stays the one
    # imported: restart the kernel after an update of the apps.
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    importlib.invalidate_caches()
    return importlib.import_module(manifest["entry"])


__all__ = ["App", "AppObject", "app", "apps", "load_runtime"]
