"""The models PlantCraft Analytics runs: built-in FMUs shipped with the app, and FMUs an administrator
published from PlantCraft Models or uploaded.

An uploaded file is kept as ``<data dir>/models/<sha256>.fmu`` (never under the name the
browser sent); a built-in one stays where the app ships it (``fmus`` of the app folder)
and is registered again at every start, so an upgrade brings its new version.
"""

from __future__ import annotations

import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from plantcraft_sdk.server.store import Store

from linkcraft.models.fmu import FmuInfo

UNPACKED = "unpacked"

MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:50] or "model"


class ModelStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS models (
        model_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        file TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size INTEGER NOT NULL,
        builtin INTEGER NOT NULL DEFAULT 0,
        info_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    """

    def __init__(self, db, folder: Path):
        super().__init__(db)
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def _row(self, row: Any) -> dict[str, Any]:
        item = self._row_with_json(row, {"info": ("info_json", {})})
        item["builtin"] = bool(item["builtin"])
        return item

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM models ORDER BY builtin DESC, name COLLATE NOCASE"
            ).fetchall()
        return [self._row(row) for row in rows]

    def signature(self) -> tuple[Any, ...]:
        """What changes whenever a model is published, renamed or removed."""

        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*), MAX(updated_at) FROM models").fetchone()
        return tuple(row)

    def get(self, model_id: str) -> dict[str, Any] | None:
        if not MODEL_ID.match(model_id or ""):
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM models WHERE model_id = ?", (model_id,)
            ).fetchone()
        return self._row(row) if row else None

    def path(self, model: dict[str, Any]) -> Path:
        """The FMU file of a model: an uploaded one under the data folder, a built-in as shipped."""

        file = Path(model["file"])
        return file if file.is_absolute() else self.folder / file

    def runnable(self, model: dict[str, Any]) -> Path:
        """The model's FMU unpacked once under ``<data dir>/models/unpacked/<sha256>``, what the
        simulation workers load. Unpacked here, not per run in ``/tmp``: the suite mounts ``/tmp``
        ``noexec``, where an FMU's library cannot be loaded, and unpacking every cycle is waste.
        """

        target = self.folder / UNPACKED / model["sha256"]
        if (target / "modelDescription.xml").is_file():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        scratch = target.parent / f".{model['sha256']}-{uuid.uuid4().hex}"
        try:
            # The archive's members were checked when it entered the library (``inspect_fmu``).
            with zipfile.ZipFile(self.path(model)) as archive:
                archive.extractall(scratch)
            try:
                scratch.rename(target)
            except OSError:
                if not (target / "modelDescription.xml").is_file():  # not another worker's copy
                    raise
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return target

    def _free_id(self, connection: Any, wanted: str) -> str:
        candidate, number = wanted, 2
        while connection.execute(
            "SELECT 1 FROM models WHERE model_id = ?", (candidate,)
        ).fetchone():
            candidate, number = f"{wanted[:56]}-{number}", number + 1
        return candidate

    def add_upload(
        self,
        temporary: Path,
        info: FmuInfo,
        sha256: str,
        *,
        name: str,
        description: str,
        by: str,
        origin: str = "",
    ) -> dict[str, Any]:
        """Keep an uploaded FMU (already inspected) as a new model. ``origin``: where it was made
        (a path on this host, such as the PlantCraft Models run that exported it)."""

        target = self.folder / f"{sha256}.fmu"
        if not target.exists():
            partial = self.folder / f".{uuid.uuid4().hex}.part"
            shutil.copyfile(temporary, partial)
            partial.replace(target)
        now = self._now()
        with self._lock, self._connect() as connection:
            model_id = self._free_id(connection, slug(name or info.name))
            connection.execute(
                "INSERT INTO models (model_id, name, description, file, sha256, size, builtin,"
                " info_json, created_at, created_by, updated_at) VALUES (?,?,?,?,?,?,0,?,?,?,?)",
                (
                    model_id,
                    (name or info.name)[:120],
                    (description or info.description)[:2000],
                    target.name,
                    sha256,
                    target.stat().st_size,
                    self._json({**info.as_dict(), **({"origin": origin} if origin else {})}),
                    now,
                    by,
                    now,
                ),
            )
        return self.get(model_id) or {}

    def register_builtin(self, model_id: str, path: Path, info: FmuInfo, sha256: str) -> None:
        """Add or refresh a model shipped with the app (same id across versions)."""

        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO models (model_id, name, description, file, sha256, size, builtin,"
                " info_json, created_at, created_by, updated_at) VALUES (?,?,?,?,?,?,1,?,?,'',?)"
                " ON CONFLICT(model_id) DO UPDATE SET name=excluded.name,"
                " description=excluded.description, file=excluded.file, sha256=excluded.sha256,"
                " size=excluded.size, builtin=1, info_json=excluded.info_json,"
                " updated_at=excluded.updated_at",
                (
                    model_id,
                    info.name,
                    info.description,
                    str(path.resolve()),
                    sha256,
                    path.stat().st_size,
                    self._json(info.as_dict()),
                    now,
                    now,
                ),
            )

    def update(self, model_id: str, *, name: str, description: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE models SET name = ?, description = ?, updated_at = ? WHERE model_id = ?",
                (name[:120], description[:2000], self._now(), model_id),
            )
        return self.get(model_id)

    def delete(self, model_id: str) -> bool:
        """Forget an uploaded model; its file goes when no other model keeps the same bytes."""

        model = self.get(model_id)
        if model is None or model["builtin"]:
            return False
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM models WHERE model_id = ?", (model_id,))
            shared = connection.execute(
                "SELECT 1 FROM models WHERE sha256 = ? AND builtin = 0", (model["sha256"],)
            ).fetchone()
        if not shared:
            self.path(model).unlink(missing_ok=True)
            shutil.rmtree(self.folder / UNPACKED / model["sha256"], ignore_errors=True)
        return True
