"""A third-party multivariable controller on the fake plant: one APC with two MVs and two CVs.

Over the six hours before ``NOW`` (10-second samples): the controller is off the first 1.5 h, so
on 75 %. ``MV-1`` (furnace duty) is in service and its target sits at its high limit 100 with a
shadow price of 2 $/h per unit: worth 2 * 1 % * 100 = 2 $/h. ``MV-2`` (feed) is out of service the
second half of the on-time (50 %). ``CV-1`` (column dP) targets 19.95 against a high limit of 20
(band 0.1) with a shadow price of -5: worth 5 * 1 % * 10 = 0.5 $/h. ``CV-2`` (outlet temperature)
is free. The limits are one sample each, two hours before the window, as a historian keeps a limit
that never moved.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from tests.plant import HOURS, NOW, SAMPLE_SECONDS, _signal, sid

CONTROLLER = "apc-c1"
VARIABLES = {
    # id: (kind, name, lo, hi, target, shadow price, unit)
    "apc-c1-mv1": ("apc_mv", "Furnace duty", 0.0, 100.0, 100.0, 2.0, "MW"),
    "apc-c1-mv2": ("apc_mv", "Feed rate", 0.0, 100.0, 50.0, None, "t/h"),
    "apc-c1-cv1": ("apc_cv", "Column dP", 10.0, 20.0, 19.95, -5.0, "kPa"),
    "apc-c1-cv2": ("apc_cv", "Outlet temperature", 300.0, 400.0, 350.0, None, "°C"),
}
PATHS = {
    "apc": ["apc"],
    "apc_mv": ["apc_variable", "apc_mv"],
    "apc_cv": ["apc_variable", "apc_cv"],
}


def _tag(asset_id: str, role: str) -> str:
    return f"{asset_id.upper()}.{role.upper()}"


def add_apc(fake, now: datetime = NOW) -> None:
    """The controller, its variables, their signals and six hours of samples, on ``fake``."""

    index = pd.date_range(now - timedelta(hours=HOURS), now, freq=f"{SAMPLE_SECONDS}s", tz="UTC")
    n = len(index)
    off = n // 4
    on = np.ones(n)
    on[:off] = 0.0
    before = pd.DatetimeIndex([index[0] - timedelta(hours=2)])
    series: dict[str, pd.Series] = {sid(_tag(CONTROLLER, "on")): pd.Series(on, index=index)}
    signals = [_signal(_tag(CONTROLLER, "on"), "APC C1 on", "")]
    assets = [
        {
            "id": CONTROLLER,
            "name": "Crude preheat APC",
            "kind": "apc",
            "type_path": PATHS["apc"],
            "parent_id": "area-a",
            "attributes": {"vendor": "Example", "cost_unit": "$/h"},
            "signals": {"on": sid(_tag(CONTROLLER, "on"))},
            "relations": [],
        }
    ]
    for asset_id, (kind, name, lo, hi, target, price, unit) in VARIABLES.items():
        roles = {"value": None, "lo": lo, "hi": hi, "target": target, "status": None}
        if price is not None:
            roles["shadow_price"] = price
        found: dict[str, str] = {}
        for role, constant in roles.items():
            tag = _tag(asset_id, role)
            found[role] = sid(tag)
            signals.append(_signal(tag, f"{name} {role}", unit))
            if role in ("lo", "hi"):
                series[sid(tag)] = pd.Series([constant], index=before)
            elif role == "value":
                series[sid(tag)] = pd.Series(
                    (lo + hi) / 2 + np.sin(np.arange(n) / 30.0), index=index
                )
            elif role == "status":
                status = np.ones(n)
                if asset_id == "apc-c1-mv2":
                    status[off + (n - off) // 2 :] = 0.0
                series[sid(tag)] = pd.Series(status, index=index)
            else:
                series[sid(tag)] = pd.Series(np.full(n, constant), index=index)
        assets.append(
            {
                "id": asset_id,
                "name": name,
                "kind": kind,
                "type_path": PATHS[kind],
                "parent_id": CONTROLLER,
                "attributes": {},
                "signals": found,
                "relations": [],
            }
        )
    fake.assets.extend(assets)
    fake.signals.extend(signals)
    fake.series_data.update(series)
