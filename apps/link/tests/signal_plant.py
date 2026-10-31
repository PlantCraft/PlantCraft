"""Signals with known data quality faults (from DataCraft), served by ``FakePlantCraft``.

Every signal is a recorded file (24 hours at 10 s, ending ``END``) with one
fault injected, so each test knows the verdict to expect.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from plantcraft_sdk.testing import FakePlantCraft

HOURS = 24
SAMPLE_SECONDS = 10
END = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
APP_KEY = "test-app-key"

USERS = {
    "admin": {"name": "Administrator", "level": "admin", "apps": {"linkcraft": "editor"}},
    "engineer": {"name": "Process Engineer", "level": "editor", "apps": {"linkcraft": "editor"}},
    "operator": {"name": "Operator", "level": "viewer", "apps": {"linkcraft": "viewer"}},
    "outsider": {"name": "No Apps", "level": "viewer", "apps": {"dashcraft": "editor"}},
}
APPS = [
    {"id": "linkcraft", "name": "PlantCraft Analytics", "url": "/link/", "version": "0.1.0"},
    {"id": "dashcraft", "name": "PlantCraft View", "url": "/dash/", "version": "0.1.0"},
]
APP_KEYS = {"linkcraft": APP_KEY, "dashcraft": "dash-key"}


def times() -> pd.DatetimeIndex:
    count = HOURS * 3600 // SAMPLE_SECONDS
    return pd.date_range(end=END, periods=count, freq=f"{SAMPLE_SECONDS}s")


def base(seed: int, level: float = 50.0) -> pd.Series:
    """A healthy process signal: a slow wave plus white noise."""

    index = times()
    rng = np.random.default_rng(seed)
    steps = np.arange(len(index))
    values = level + 4.0 * np.sin(2 * np.pi * steps / 2600) + rng.normal(0, 0.3, len(index))
    return pd.Series(values, index=index)


SOURCE = "historian"


def _signal(tag: str, name: str, unit: str = "%", low=0.0, high=100.0) -> dict:
    # API v1 ids are <source id>:<tag> (D2); Analytics never builds them from a tag.
    return {
        "id": f"{SOURCE}:{tag}",
        "name": name,
        "source": SOURCE,
        "unit": unit,
        "description": name,
        "low": low,
        "high": high,
    }


def plant_series() -> dict[str, pd.Series]:
    series: dict[str, pd.Series] = {}
    series["TI-100.PV"] = base(1)
    frozen = base(2)
    frozen.iloc[3000:5000] = frozen.iloc[3000]
    series["TI-101.PV"] = frozen
    spiky = base(3)
    spiky.iloc[[500, 1800, 4400, 6100, 7900]] += 35.0
    series["PI-102.PV"] = spiky
    gappy = base(4)
    series["FI-103.PV"] = gappy.drop(gappy.index[2000:4500])
    stale = base(5)
    series["LI-104.PV"] = stale.iloc[: len(stale) - 1200]
    high = base(6, level=101.0)
    series["PI-105.PV"] = high
    noisy = base(7) + np.random.default_rng(70).normal(0, 4.0, len(times()))
    series["FI-106.PV"] = noisy
    series["TI-107.PV"] = (base(8) / 5.0).round(0) * 5.0
    reference = base(9)
    series["TI-108A.PV"] = reference + np.linspace(0.0, 9.0, len(reference))
    series["TI-108B.PV"] = reference + np.random.default_rng(90).normal(0, 0.05, len(reference))
    # A loop: its setpoint is constant by design, its mode is text.
    series["FIC-110.PV"] = base(10)
    series["FIC-110.SP"] = pd.Series(50.0, index=times())
    series["FIC-110.OP"] = base(11, level=40.0)
    labels = np.where(np.arange(len(times())) % 3000 < 2800, "AUTO", "MAN")
    series["FIC-110.MODE"] = pd.Series(labels, index=times())
    return series


SIGNALS = [
    _signal("TI-100.PV", "Reactor inlet temperature", "degC"),
    _signal("TI-101.PV", "Reactor outlet temperature", "degC"),
    _signal("PI-102.PV", "Header pressure", "bar"),
    _signal("FI-103.PV", "Steam flow", "t/h"),
    _signal("LI-104.PV", "Tank level"),
    _signal("PI-105.PV", "Discharge pressure", "bar"),
    _signal("FI-106.PV", "Cooling water flow", "m3/h"),
    _signal("TI-107.PV", "Jacket temperature", "degC"),
    _signal("TI-108A.PV", "Bed temperature A", "degC"),
    _signal("TI-108B.PV", "Bed temperature B", "degC"),
    _signal("FIC-110.PV", "Feed flow", "m3/h"),
    _signal("FIC-110.SP", "Feed flow setpoint", "m3/h"),
    _signal("FIC-110.OP", "Feed valve output"),
    {**_signal("FIC-110.MODE", "Feed flow mode", "", None, None), "kind": "text"},
]
# The verdict each signal should get, and the check that limits it.
EXPECTED = {
    "historian:TI-100.PV": ("good", None),
    "historian:TI-101.PV": ("suspect", "sq_frozen"),
    "historian:PI-102.PV": ("suspect", "sq_spikes"),
    "historian:FI-103.PV": ("bad", "sq_availability"),
    "historian:LI-104.PV": ("bad", "sq_freshness"),
    "historian:PI-105.PV": ("bad", "sq_range"),
    "historian:FI-106.PV": ("bad", "sq_noise"),
    "historian:TI-107.PV": ("suspect", "sq_resolution"),
    "historian:FIC-110.SP": ("good", None),
    "historian:FIC-110.MODE": ("good", None),
}
ASSETS = [
    {"id": "plant", "name": "Plant", "kind": "site", "parent_id": None, "attributes": {}},
    {
        "id": "fic-110",
        "name": "FIC-110",
        "kind": "loop",
        "parent_id": "plant",
        "attributes": {"description": "Feed flow control"},
        "signals": {
            "pv": "historian:FIC-110.PV",
            "sp": "historian:FIC-110.SP",
            "op": "historian:FIC-110.OP",
            "mode": "historian:FIC-110.MODE",
        },
    },
]


def make_signal_fake() -> FakePlantCraft:
    return FakePlantCraft(
        users=USERS,
        apps=APPS,
        app_keys=APP_KEYS,
        assets=ASSETS,
        signals=SIGNALS,
        series=plant_series(),
        now=END,
    )
