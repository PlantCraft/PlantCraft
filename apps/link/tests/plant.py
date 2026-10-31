"""Loop-shaped synthetic plant data with known faults, served by ``FakePlantCraft``.

The SDK's fake gives every signal a generic wave; CPM needs loops whose answer
is known. Each loop here is built so one diagnosis is clearly right:

| Loop | Built as | Expected |
|---|---|---|
| ``FIC-101`` | PV tracks SP closely, small noise | healthy (normal) |
| ``LIC-102`` | sustained 5-minute oscillation of PV and OP | oscillation flagged |
| ``PIC-103`` | OP pinned at 100 % with PV far below SP | output saturation |
| ``TIC-104`` | PV frozen at one value | data rejected by the gate |
| ``FIC-105`` | valve stick-slip: OP sticks then jumps, PV cycles | stiction screening flags it |

Signal ids are as API v1 names them, ``<source id>:<tag>`` (``fake:FIC-101.PV``, ``sid``).
``make_fake(catalog=True)`` serves the same plant as PlantCraft's asset catalog does
(``type_path``, loop attributes, relations and ``GET /api/v1/asset-types``), plus ``FIC-106``,
a loop asset whose OP was never bound: an incomplete record. ``make_fake(older=True)`` is a
PlantCraft from before the asset catalog and the suite endpoints.
"""

from __future__ import annotations

import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from plantcraft_sdk.assets import resolve_types, starter_types
from plantcraft_sdk.testing import FakePlantCraft, FakeResponse

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
HOURS = 6
SAMPLE_SECONDS = 10

MANIFEST = tomllib.loads((Path(__file__).resolve().parents[1] / "app.toml").read_text())


def _index(now: datetime = NOW, hours: float = HOURS) -> pd.DatetimeIndex:
    start = now - timedelta(hours=hours)
    return pd.date_range(start, now, freq=f"{SAMPLE_SECONDS}s", tz="UTC")


# The source the fake plant's signals are read from: API v1 names a signal ``<source id>:<tag>``.
SOURCE = "fake"


def sid(tag: str) -> str:
    """The API v1 id of one of this plant's signals (``fake:FIC-101.PV``)."""

    return f"{SOURCE}:{tag}"


def _signal(tag: str, name: str, unit: str = "%") -> dict:
    return {
        "id": sid(tag),
        "name": name,
        "source": SOURCE,
        "unit": unit,
        "description": name,
        "low": 0.0,
        "high": 100.0,
    }


def loop_series(now: datetime = NOW) -> dict[str, pd.Series]:
    index = _index(now)
    n = len(index)
    rng = np.random.default_rng(7)
    seconds = np.arange(n) * SAMPLE_SECONDS
    data: dict[str, np.ndarray] = {}

    # FIC-101: healthy tracking, one SP step, first-order response.
    sp = np.where(seconds < seconds[-1] / 2, 50.0, 55.0)
    pv = np.empty(n)
    pv[0] = 50.0
    for i in range(1, n):
        pv[i] = pv[i - 1] + 0.3 * (sp[i] - pv[i - 1])
    pv += rng.normal(0, 0.05, n)
    data.update(
        {
            "FIC-101.PV": pv,
            "FIC-101.SP": sp,
            "FIC-101.OP": 40 + 2 * (sp - 50),
            "FIC-101.MODE": np.ones(n),
        }
    )

    # LIC-102: sustained oscillation with a 300 s period.
    wave = np.sin(2 * np.pi * seconds / 300.0)
    data.update(
        {
            "LIC-102.PV": 50 + 4 * wave + rng.normal(0, 0.1, n),
            "LIC-102.SP": np.full(n, 50.0),
            "LIC-102.OP": 45 + 8 * np.sin(2 * np.pi * seconds / 300.0 - 1.2),
        }
    )

    # PIC-103: output pinned at the limit, PV far below SP.
    data.update(
        {
            "PIC-103.PV": 30 + rng.normal(0, 0.3, n),
            "PIC-103.SP": np.full(n, 60.0),
            "PIC-103.OP": np.full(n, 100.0),
        }
    )

    # TIC-104: frozen PV (a dead transmitter).
    data.update(
        {
            "TIC-104.PV": np.full(n, 71.25),
            "TIC-104.SP": np.full(n, 70.0),
            "TIC-104.OP": 35 + rng.normal(0, 0.5, n),
        }
    )

    # FIC-105: stick-slip valve. The OP sticks for a minute, then jumps one step;
    # the PV cycles slowly with it (flat-then-jump OP plus an oscillating PV).
    levels = np.concatenate([np.arange(46, 54), np.arange(54, 46, -1)]).astype(float)
    op = levels[(np.arange(n) // 6) % len(levels)]
    period = 6 * len(levels) * SAMPLE_SECONDS
    pv = 50 + 3 * np.sin(2 * np.pi * (seconds - period / 4) / period) + rng.normal(0, 0.05, n)
    data.update({"FIC-105.PV": pv, "FIC-105.SP": np.full(n, 50.0), "FIC-105.OP": op})

    return {sid(tag): pd.Series(values, index=index) for tag, values in data.items()}


LOOPS = {
    "FIC-101": ("Feed flow", True),
    "LIC-102": ("Drum level", False),
    "PIC-103": ("Header pressure", False),
    "TIC-104": ("Reactor temperature", False),
    "FIC-105": ("Reflux flow", False),
}


def assets() -> list[dict]:
    items: list[dict] = [
        {"id": "plant", "name": "Plant", "kind": "site", "parent_id": None, "attributes": {}},
        {
            "id": "unit-100",
            "name": "Unit 100",
            "kind": "unit",
            "parent_id": "plant",
            "attributes": {},
        },
        {
            "id": "area-a",
            "name": "Area A",
            "kind": "area",
            "parent_id": "unit-100",
            "attributes": {},
        },
    ]
    for loop_id, (name, has_mode) in LOOPS.items():
        signals = {role: sid(f"{loop_id}.{role.upper()}") for role in ("pv", "sp", "op")}
        if has_mode:
            signals["mode"] = sid(f"{loop_id}.MODE")
        items.append(
            {
                "id": loop_id.lower(),
                "name": loop_id,
                "kind": "loop",
                "parent_id": "area-a",
                "attributes": {"description": name},
                "signals": signals,
            }
        )
    return items


def signals() -> list[dict]:
    found = []
    for loop_id, (name, has_mode) in LOOPS.items():
        for role in ("PV", "SP", "OP") + (("MODE",) if has_mode else ()):
            found.append(_signal(f"{loop_id}.{role}", f"{name} {role}"))
    return found


# Asset types as an admin writes them in PlantCraft (own attributes and roles; ``children``
# names the types that may sit inside): the starter types, Control loop (``loop``) among them,
# plus a ``cascade_loop`` derived from it. The SDK's fake answers ``GET /api/v1/asset-types``
# with them resolved (inherited roles filled in, ``path`` root first), as PlantCraft does.
ASSET_TYPES = [
    *starter_types(),
    {
        "id": "cascade_loop",
        "name": "Cascade loop",
        "description": "A loop whose setpoint another loop moves.",
        "icon": "gauge",
        "parent": "loop",
        "attributes": [],
        "roles": [],
        "children": [],
    },
]
# ``GET /api/v1/asset-types`` as PlantCraft answers it.
RESOLVED_TYPES = resolve_types(ASSET_TYPES)

# Catalog attributes of the plant's loops (only FIC-101 and PIC-103 carry a loop type, so the
# other loops keep the generic protocol the known-fault expectations were written for).
CATALOG = {
    "fic-101": {
        "loop_type": "flow",
        "criticality": "high",
        "action": "reverse",
        "controller": "DCS",
    },
    "pic-103": {"loop_type": "pressure", "criticality": "low", "controller": "SLC"},
}


# The fake's people and app key, for Analytics (the SDK's defaults name an older app id).
APP_ID = "linkcraft"
APPS = [{"id": APP_ID, "name": "PlantCraft Analytics", "url": "/link/", "version": "0.1.0"}]
USERS = {
    "admin": {"name": "Administrator", "level": "admin", "apps": {APP_ID: "editor"}},
    "engineer": {"name": "Process Engineer", "level": "editor", "apps": {APP_ID: "editor"}},
    "operator": {"name": "Operator", "level": "viewer", "apps": {APP_ID: "viewer"}},
    "outsider": {"name": "No Apps", "level": "viewer", "apps": {}},
}
APP_KEYS = {APP_ID: "test-app-key"}


class PlantFake(FakePlantCraft):
    """The SDK's fake, with a recorded file's end taken from the file alone.

    PlantCraft answers "now" for a recorded file with the file's last sample
    (``Platform.data_end``); derived series an app wrote are not part of the file. The fake of
    SDK 0.7.0 takes the last sample of every series it holds, derived ones too, so a health point
    written at the round time would move the recorded plant's "now" to the wall clock and empty
    the next round's window. Drop this class once the SDK's fake leaves derived series out.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("users", USERS)
        kwargs.setdefault("apps", APPS)
        kwargs.setdefault("app_keys", APP_KEYS)
        super().__init__(**kwargs)
        # Link may write only the events its app.toml declares (the fake refuses the others).
        self.declare_events(MANIFEST)

    @property
    def data_end(self) -> datetime:
        if self.recorded:
            ends = [
                pd.Timestamp(values.index.max())
                for signal_id, values in self.series_data.items()
                if signal_id not in self.derived and len(values)
            ]
            ends = [stamp for stamp in ends if not pd.isna(stamp)]
            if ends:
                return max(
                    stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
                    for stamp in ends
                ).to_pydatetime()
        return self.now


class OlderPlantCraft(PlantFake):
    """PlantCraft before the asset catalog and the suite endpoints (before 2026-10-20).

    Assets have no ``type_path`` or ``relations``; ``GET /api/v1/asset-types``, results,
    events, runs, schedules and derived series (``PUT /api/v1/series``) answer 404, as a server
    without those routes does.
    """

    MISSING = ("/api/v1/asset-types", "/api/v1/results", "/api/v1/events", "/api/v1/runs")
    MISSING += ("/api/v1/schedules",)

    def handle(self, method, path, **kwargs):
        if path.startswith(self.MISSING) or (method == "PUT" and path == "/api/v1/series"):
            self.requests += 1
            return FakeResponse(404, {"detail": "Not Found"})
        answer = super().handle(method, path, **kwargs)
        if answer.status == 200 and path.startswith("/api/v1/assets"):
            items = answer.body if isinstance(answer.body, list) else [answer.body]
            for item in items:
                item.pop("type_path", None)
                item.pop("relations", None)
        return answer


def catalog_assets() -> list[dict]:
    items = []
    for item in assets():
        item = dict(item)
        if item["kind"] == "loop":
            item["attributes"] = {**item["attributes"], **CATALOG.get(item["id"], {})}
        items.append(item)
    for item in items:
        if item["id"] == "fic-101":
            item["relations"] = [{"type": "feeds", "to": "pic-103"}]
    items.append(
        {
            "id": "fic-106",
            "name": "FIC-106",
            "kind": "loop",
            "parent_id": "area-a",
            "attributes": {"description": "Steam flow", "loop_type": "flow"},
            "signals": {"pv": sid("FIC-106.PV"), "sp": sid("FIC-106.SP")},
        }
    )
    return items


def catalog_series(now: datetime = NOW) -> dict:
    series = loop_series(now)
    series[sid("FIC-106.PV")] = series[sid("FIC-101.PV")]
    series[sid("FIC-106.SP")] = series[sid("FIC-101.SP")]
    return series


def catalog_signals() -> list[dict]:
    return signals() + [_signal("FIC-106.PV", "Steam flow PV"), _signal("FIC-106.SP", "Steam SP")]


def make_fake(now: datetime = NOW, *, catalog: bool = False, older: bool = False) -> FakePlantCraft:
    """The known-fault plant on the SDK's fake PlantCraft.

    ``catalog``: the plant as PlantCraft's asset catalog describes it (loop attributes,
    relations, FIC-106 and the ``cascade_loop`` type). ``older``: a PlantCraft from before the
    asset catalog and the suite endpoints (``OlderPlantCraft``). Results, events, runs and
    schedules land in ``fake.links``.
    """

    if older:
        return OlderPlantCraft(assets=assets(), signals=signals(), series=loop_series(now), now=now)
    if not catalog:
        return PlantFake(assets=assets(), signals=signals(), series=loop_series(now), now=now)
    return PlantFake(
        assets=catalog_assets(),
        signals=catalog_signals(),
        series=catalog_series(now),
        now=now,
        asset_types=ASSET_TYPES,
    )


def publish(fake: FakePlantCraft, app: str, rows: list[dict]) -> dict:
    """Results another app (DataCraft...) publishes to the fake, with that app's own key."""

    fake.app_keys.setdefault(app, f"{app}-key")
    with fake.client(None, app=app, key=fake.app_keys[app]) as client:
        return client.put_results(rows)
