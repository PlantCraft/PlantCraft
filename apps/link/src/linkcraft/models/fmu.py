"""Reading an FMU file (FMI 2.0 or 3.0) without running it: what it is, its variables and
whether this server can run it.

An FMU is a zip with ``modelDescription.xml`` and native binaries per platform. This module
only opens the zip and reads the XML (through FMPy); the native code runs only in the
simulation workers (``linkcraft.models.simulate``). A file that is not a sane zip, holds an
absurd number of members or expands past ``MAX_EXPANDED_BYTES`` is refused before FMPy reads it.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from linkcraft.i18n import t

MAX_MEMBERS = 20_000
MAX_EXPANDED_BYTES = 1_000_000_000
# The causalities a model block shows: inputs and outputs become ports, parameters parameters.
ROLES = ("input", "output", "parameter")


class FmuError(ValueError):
    """A file that is not an FMU PlantCraft Analytics can use, with a sentence a person can act on."""


@dataclass
class FmuInfo:
    name: str
    description: str
    fmi_version: str
    fmi_types: list[str]
    model_identifier: str
    generation_tool: str
    platforms: list[str]
    runs_here: bool
    step_seconds: float | None
    variables: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "fmi_version": self.fmi_version,
            "fmi_types": self.fmi_types,
            "model_identifier": self.model_identifier,
            "generation_tool": self.generation_tool,
            "platforms": self.platforms,
            "runs_here": self.runs_here,
            "step_seconds": self.step_seconds,
            "variables": self.variables,
        }


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_MEMBERS:
                raise FmuError(t("This FMU holds too many files to be a model."))
            if sum(member.file_size for member in members) > MAX_EXPANDED_BYTES:
                raise FmuError(t("This FMU expands to more than 1 GB; it is refused."))
            names = {member.filename for member in members}
            if "modelDescription.xml" not in names:
                raise FmuError(t("This file has no modelDescription.xml: it is not an FMU."))
            for name in names:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise FmuError(t("This FMU has a file outside its own folder; it is refused."))
    except zipfile.BadZipFile as exc:
        raise FmuError(t("This file is not an FMU (an FMU is a zip archive).")) from exc


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _variable(item: Any) -> dict[str, Any] | None:
    causality = getattr(item, "causality", None)
    if causality not in ROLES:
        return None
    if causality == "parameter" and getattr(item, "variability", None) not in ("fixed", "tunable"):
        return None
    kind = str(getattr(item, "type", "") or "")
    return {
        "name": item.name,
        "causality": causality,
        "type": kind,
        "numeric": kind in ("Real", "Float64", "Float32", "Integer", "Int32", "Int64"),
        "description": getattr(item, "description", None) or "",
        "unit": getattr(item, "unit", None) or "",
        "start": _number(getattr(item, "start", None)),
    }


def inspect_fmu(path: Path) -> FmuInfo:
    """What an FMU is, read from its ``modelDescription.xml``; ``FmuError`` when it is not one."""

    path = Path(path)
    _check_zip(path)
    import fmpy
    from fmpy import read_model_description, supported_platforms

    try:
        description = read_model_description(str(path), validate=True)
    except Exception as exc:  # noqa: BLE001 - FMPy raises many kinds for a broken file
        raise FmuError(
            t("The model description of this FMU is not valid: {error}", error=str(exc)[:300])
        ) from exc
    types = []
    if description.coSimulation is not None:
        types.append("cs")
    if description.modelExchange is not None:
        types.append("me")
    if not types:
        raise FmuError(t("This FMU offers neither co-simulation nor model exchange."))
    interface = description.coSimulation or description.modelExchange
    platforms = sorted(supported_platforms(str(path)))
    here = {fmpy.platform, fmpy.platform_tuple}
    variables = [found for found in map(_variable, description.modelVariables) if found]
    experiment = description.defaultExperiment
    return FmuInfo(
        name=description.modelName or path.stem,
        description=description.description or "",
        fmi_version=str(description.fmiVersion),
        fmi_types=types,
        model_identifier=interface.modelIdentifier,
        generation_tool=description.generationTool or "",
        platforms=platforms,
        runs_here=bool(here & set(platforms)),
        step_seconds=_number(getattr(experiment, "stepSize", None)) if experiment else None,
        variables=variables,
    )
