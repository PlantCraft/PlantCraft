"""The FMUs shipped with PlantCraft Analytics (``fmus/<machine>`` of the app folder), registered at
start.

They are PlantCraft Models' ``PlantCraftTwin`` package (Modelica) exported with OpenModelica,
once per machine: FMI 2.0 names both 64-bit Linux builds ``linux64``, so an x86-64 and an arm64
binary cannot share one FMU. They came from PlantCraft Twin with the twins themselves.
"""

from __future__ import annotations

import logging
import platform
from functools import cache
from pathlib import Path
from typing import Any

from linkcraft.config import CHECKOUT
from linkcraft.models.fmu import FmuError, inspect_fmu, sha256_of
from linkcraft.models.store import ModelStore, slug

LOGGER = logging.getLogger(__name__)


# platform.machine() spellings of the two machines the FMUs are built for.
MACHINES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}


def builtin_folder() -> Path:
    """``fmus/<machine>`` of the source checkout, else of the image (``/app``)."""

    machine = MACHINES.get(platform.machine().lower(), platform.machine().lower())
    for root in (CHECKOUT, Path("/app")):
        folder = root / "fmus" / machine
        if folder.is_dir():
            return folder
    return CHECKOUT / "fmus" / machine


@cache
def _builtin_models(folder: Path) -> tuple[dict[str, Any], ...]:
    found = []
    for path in sorted(folder.glob("*.fmu")) if folder.is_dir() else []:
        try:
            info = inspect_fmu(path)
        except FmuError:
            continue
        found.append(
            {
                "model_id": slug(path.stem),
                "name": info.name,
                "description": info.description,
                "builtin": True,
                "info": info.as_dict(),
            }
        )
    return tuple(found)


def builtin_models() -> list[dict[str, Any]]:
    """The shipped models as the block catalog reads them, before any store exists: their
    blocks are always in the catalog, so the algorithms Link ships with them always check."""

    return list(_builtin_models(builtin_folder()))


def register_builtins(models: ModelStore, folder: Path | None = None) -> int:
    """Register every ``*.fmu`` of ``folder``; the model id is the file name as a slug."""

    folder = folder or builtin_folder()
    if not folder.is_dir():
        return 0
    count = 0
    for path in sorted(folder.glob("*.fmu")):
        try:
            info = inspect_fmu(path)
        except FmuError as exc:
            LOGGER.warning("Built-in model %s not registered: %s", path.name, exc)
            continue
        models.register_builtin(slug(path.stem), path, info, sha256_of(path))
        count += 1
    return count
