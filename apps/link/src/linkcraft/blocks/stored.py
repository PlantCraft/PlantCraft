"""How an algorithm is stored (``catalog.presets``), and the conversion of 0.2 protocols."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plantcraft_sdk.blocks import ALGORITHM_FIELDS, AlgorithmDocs

from linkcraft.blocks.algorithms import SYSTEM
from linkcraft.blocks.convert import diagram_of, methods_in, parameters_in

# Where an algorithm's work runs on the suite's compute workers (PlantCraft docs/compute.md):
# the executor's environment (an image with more packages than Analytics' own) and the size of
# machine it needs.
DEFAULT_PLACEMENT = {"environment": "standard", "size": "small"}
SIZES = ("small", "medium", "large")


def compute_placement(value: Any) -> dict[str, str]:  # noqa: ANN401
    """``{"environment", "size"}`` from what was stored or sent; the defaults for anything else."""

    found = value if isinstance(value, Mapping) else {}
    environment = str(found.get("environment") or "").strip().lower() or "standard"
    if not (
        len(environment) <= 40
        and environment[0].isalnum()
        and all(c.isalnum() or c == "-" for c in environment)
    ):
        environment = "standard"
    size = str(found.get("size") or "").strip().lower()
    return {"environment": environment, "size": size if size in SIZES else "small"}


# Fields of a 0.2 protocol's documentation -> the algorithm's.
OLD_DOCS = {"summary": "purpose", "inputs": "assets", "reading": "reading", "prompt": "assistant"}


def method_config(
    diagram: Mapping[str, Any],
    docs: AlgorithmDocs | Mapping[str, Any] | None = None,
    subject_kind: str = "loop",
    *,
    timing: Mapping[str, Any] | None = None,
    assets: list[str] | None = None,
    compute: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """An algorithm's stored configuration: its diagram, its docs and what the diagram runs.

    An algorithm on assets also keeps its ``timing`` (cycle, window and step) and the
    ``assets`` it runs on. ``compute`` is where its work runs (``compute_placement``), kept
    when it is not the default.
    """

    if isinstance(docs, AlgorithmDocs):
        written = docs.model_dump()
    else:
        written = {key: str((docs or {}).get(key) or "").strip() for key in ALGORITHM_FIELDS}
    config = {
        "diagram": dict(diagram),
        "docs": {key: value for key, value in written.items() if value},
        "subject_kind": subject_kind,
        "method_ids": methods_in(diagram),
        "parameters": parameters_in(diagram),
    }
    if subject_kind == "asset":
        config["timing"] = dict(timing or {})
        config["assets"] = list(assets or [])
    placement = compute_placement(compute)
    if placement != DEFAULT_PLACEMENT:
        config["compute"] = placement
    return config


def system_rows() -> list[dict[str, Any]]:
    return [
        {
            "algorithm_id": item["algorithm_id"],
            "name": item["name"],
            "description": item["description"],
            "tags": list(item.get("tags") or []),
            "version": int(item.get("version") or 1),
            "method_config": method_config(
                item["diagram"], item["docs"], item["subject_kind"], timing={}, assets=[]
            ),
        }
        for item in SYSTEM
    ]


def converted(config: Mapping[str, Any]) -> dict[str, Any] | None:
    """A 0.2 protocol's configuration as an algorithm's; None when it already is one."""

    if isinstance(config.get("diagram"), Mapping):
        return None
    old = config.get("docs") if isinstance(config.get("docs"), Mapping) else {}
    docs = {new: str(old.get(key) or "") for key, new in OLD_DOCS.items()}
    if docs["purpose"]:
        # The purpose is one sentence: the summary's first.
        first = docs["purpose"].split(". ")[0].strip().rstrip(".")
        docs["purpose"] = f"{first}." if first else ""
    return method_config(diagram_of(config), docs, str(config.get("subject_kind") or "loop"))


def convert_stored(presets: Any) -> int:
    """Convert every 0.2 protocol a person saved; returns how many were converted."""

    count = 0
    for profile in presets.list_profiles():
        if profile.get("system"):
            continue
        config = converted(profile.get("method_config") or {})
        if config is None:
            continue
        presets.save_profile(
            profile_id=profile["profile_id"],
            name=profile["name"],
            description=profile.get("description") or "",
            method_config=config,
        )
        count += 1
    return count
