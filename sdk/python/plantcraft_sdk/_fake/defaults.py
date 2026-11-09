"""The fake PlantCraft's default users, apps, groups, assets and signals, and its synthetic series."""

import math
import zlib
from typing import Any

import numpy as np
import pandas as pd

from plantcraft_sdk.refs import split_signal_id

BASE_URL = "http://processcraft.test"


SESSION_COOKIE = "processcraft_session"


DEFAULT_APPS: list[dict[str, Any]] = [
    {"id": "linkcraft", "name": "PlantCraft Analytics", "url": "/link/", "version": "0.1.0"},
]


DEFAULT_USERS: dict[str, dict[str, Any]] = {
    "admin": {"name": "Administrator", "level": "admin", "apps": {"linkcraft": "editor"}},
    "engineer": {"name": "Process Engineer", "level": "editor", "apps": {"linkcraft": "editor"}},
    "operator": {"name": "Operator", "level": "viewer", "apps": {"linkcraft": "viewer"}},
    "outsider": {"name": "No Apps", "level": "viewer", "apps": {}},
}


DEFAULT_APP_KEYS = {"linkcraft": "test-app-key"}


DEFAULT_GROUPS: list[dict[str, Any]] = [
    {"id": "operations", "name": "Operations", "kind": "team", "members": ["operator"]},
    {
        "id": "process-engineering",
        "name": "Process engineering",
        "kind": "discipline",
        "coordinator": "engineer",
        "members": ["engineer", "admin"],
    },
]


DEFAULT_ASSETS: list[dict[str, Any]] = [
    {"id": "plant", "name": "Plant", "kind": "site", "parent_id": None, "attributes": {}},
    {"id": "unit-100", "name": "Unit 100", "kind": "unit", "parent_id": "plant", "attributes": {}},
    {
        "id": "fv-101",
        "name": "FV-101",
        "kind": "control_valve",
        "parent_id": "unit-100",
        "attributes": {"description": "Feed valve", "characteristic": "equal percentage"},
    },
    {
        "id": "fic-101",
        "name": "FIC-101",
        "kind": "loop",
        "parent_id": "unit-100",
        "attributes": {
            "description": "Feed flow control",
            "loop_type": "flow",
            "criticality": "high",
            "action": "reverse",
            "controller": "DCS",
        },
        "relations": [{"type": "controls", "to": "fv-101"}],
        "signals": {
            "pv": "fake:FIC-101.PV",
            "sp": "fake:FIC-101.SP",
            "op": "fake:FIC-101.OP",
            "mode": "fake:FIC-101.MODE",
        },
    },
    {
        "id": "lic-102",
        "name": "LIC-102",
        "kind": "loop",
        "parent_id": "unit-100",
        "attributes": {"description": "Drum level control", "loop_type": "level"},
        "signals": {"pv": "fake:LIC-102.PV", "sp": "fake:LIC-102.SP", "op": "fake:LIC-102.OP"},
    },
]


# The source id of the fake's own signals.
FAKE_SOURCE = "fake"


def _signal(tag: str, name: str, unit: str, low: float | None, high: float | None) -> dict:
    # No "kind": the fake answers it from the given series (labels are text), else "number".
    return {
        "id": f"{FAKE_SOURCE}:{tag}",
        "name": name,
        "source": FAKE_SOURCE,
        "unit": unit,
        "description": name,
        "low": low,
        "high": high,
        # The fake's signals read like an OPC UA source's (no laboratory sampling).
        "source_kind": "opcua",
    }


DEFAULT_SIGNALS: list[dict[str, Any]] = [
    _signal("FIC-101.PV", "Feed flow", "m3/h", 0.0, 100.0),
    _signal("FIC-101.SP", "Feed flow setpoint", "m3/h", 0.0, 100.0),
    _signal("FIC-101.OP", "Feed valve output", "%", 0.0, 100.0),
    _signal("FIC-101.MODE", "Feed flow mode (1 auto)", "", None, None),
    _signal("LIC-102.PV", "Drum level", "%", 0.0, 100.0),
    _signal("LIC-102.SP", "Drum level setpoint", "%", 0.0, 100.0),
    _signal("LIC-102.OP", "Drum outlet valve", "%", 0.0, 100.0),
]


def synthetic(signal_id: str, times: pd.DatetimeIndex) -> np.ndarray:
    """A deterministic process-like signal: a level, a slow wave and repeatable noise.

    Seeded by the tag, so ``fake:FIC-101.PV`` and ``FIC-101.PV`` draw the same values.
    """

    signal_id = split_signal_id(signal_id)[1]
    seed = zlib.crc32(signal_id.encode()) % 1000
    seconds = times.as_unit("ns").asi8 / 1e9 if len(times) else np.array([])
    suffix = signal_id.rsplit(".", 1)[-1].upper()
    if suffix == "MODE":
        return np.ones(len(times))
    if suffix == "SP":
        return 50.0 + 5.0 * (np.floor(seconds / 3600.0) % 2)
    level = 40.0 if suffix == "OP" else 50.0
    wave = 3.0 * np.sin(2 * math.pi * seconds / (600.0 + seed))
    noise = (np.sin(seconds * 12.9898 + seed) * 43758.5453) % 1.0 - 0.5
    return level + wave + noise


def synthetic_text(signal_id: str, times: pd.DatetimeIndex) -> list[str]:
    """A text signal with no given series: a controller left in automatic."""

    return ["AUTO"] * len(times)
