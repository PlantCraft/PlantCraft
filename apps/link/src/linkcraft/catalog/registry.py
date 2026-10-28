"""Registry of the methods LinkCraft runs, grouped by role.

Two groups ship with LinkCraft:

- ``data_quality`` (``ROLE = "gate"``): availability, value integrity and
  statistics. They run first on every loop and report ``metrics["apt"]``; the
  CPM methods only run on data the gate accepts.
- ``cpm``: the control loop performance methods.

Every method is a module (or an ``@method`` function from
``plantcraft_sdk.methods``) with ``METHOD_SPEC``, ``run`` and optionally
``describe(metrics)``, the one place its finding is worded for people.
"""

from __future__ import annotations

from typing import Any, Protocol

from plantcraft_sdk.methods import MethodBlockSpec, MethodResult
from pydantic import BaseModel

from linkcraft.i18n import t
from linkcraft.methods import cpm as cpm_methods
from linkcraft.methods import quality as quality_methods


class MethodModule(Protocol):
    METHOD_SPEC: MethodBlockSpec

    def run(self, input_data: BaseModel, parameters: BaseModel) -> MethodResult: ...


GATE = "data_quality"
CPM = "cpm"
# Texts are English constants; they go through t() when served.
GROUPS: dict[str, dict[str, Any]] = {
    GATE: {
        "group_id": GATE,
        "name": "Loop data gate",
        "description": "Whether the loop's signals arrive and can be trusted in the analysed "
        "window: gaps, frozen or invalid values and window statistics. Runs before every loop "
        "protocol, unless the Signal quality protocol already judged every signal of the loop.",
        "role": "gate",
        "modules": quality_methods.METHOD_MODULES,
    },
    CPM: {
        "group_id": CPM,
        "name": "Control loop performance",
        "description": "Setpoint tracking, oscillation, valve, saturation, noise and operating mode.",
        "role": "analysis",
        "modules": cpm_methods.METHOD_MODULES,
    },
}

METHOD_MODULES: dict[str, MethodModule] = {}
METHOD_GROUP: dict[str, str] = {}
for _group_id, _group in GROUPS.items():
    for _module in _group["modules"]:
        _method_id = _module.METHOD_SPEC.method_id
        if _method_id in METHOD_MODULES:
            raise ValueError(f"Duplicate method id {_method_id!r}")
        METHOD_MODULES[_method_id] = _module
        METHOD_GROUP[_method_id] = _group_id

METHOD_SPECS: dict[str, MethodBlockSpec] = {
    method_id: module.METHOD_SPEC for method_id, module in METHOD_MODULES.items()
}


def list_method_specs(group: str | None = None) -> list[MethodBlockSpec]:
    """Every method, or only those of one group (``"cpm"``, ``"data_quality"``)."""

    return [
        spec
        for method_id, spec in METHOD_SPECS.items()
        if group is None or METHOD_GROUP.get(method_id) == group
    ]


def method_group(method_id: str) -> str | None:
    return METHOD_GROUP.get(method_id)


def gate_method_ids() -> list[str]:
    """Methods that decide whether a loop's data is fit for analysis."""

    gates = {key for key, item in GROUPS.items() if item["role"] == "gate"}
    return [method_id for method_id, group in METHOD_GROUP.items() if group in gates]


def group_catalog() -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for group in METHOD_GROUP.values():
        counts[group] = counts.get(group, 0) + 1
    return [
        {
            "group_id": key,
            "name": t(item["name"]),
            "description": t(item["description"]),
            "role": item["role"],
            "method_count": counts.get(key, 0),
        }
        for key, item in GROUPS.items()
    ]


def get_method_spec(method_id: str) -> MethodBlockSpec:
    return METHOD_SPECS[method_id]


def method_name(method_id: str) -> str:
    """The name people read of a method ("Possible valve stiction screening"), else its id."""

    spec = METHOD_SPECS.get(method_id)
    return t(spec.name) if spec is not None and getattr(spec, "name", "") else method_id


def get_method_module(method_id: str) -> MethodModule:
    return METHOD_MODULES[method_id]


def describe_result(result: dict[str, Any]) -> str:
    """One sentence of what the method measured, from its ``describe(metrics)``.

    Falls back to the result's own message, so methods without one still say
    something; a wording bug never hides the result.
    """

    message = str(result.get("message") or "").strip()
    if result.get("status") in {"insufficient_data", "not_applicable"}:
        return message
    describe = getattr(METHOD_MODULES.get(str(result.get("method_id"))), "describe", None)
    if describe is None:
        return message
    try:
        return describe(result.get("metrics") or {})
    except Exception:
        return message
