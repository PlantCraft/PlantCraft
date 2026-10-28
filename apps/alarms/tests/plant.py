"""The plant tests read: the suite's test plant (``plantcraft_sdk.testplant``: the Simulator's
loops as assets and 12 hours of their signals ending at ``NOW``) served to PlantCraft Alarms,
and its four users (admin, engineer, operator, outsider)."""

from __future__ import annotations

from plantcraft_sdk.testing import FakePlantCraft
from plantcraft_sdk.testplant import (
    APP_KEY,
    HOURS,
    NOW,
    SOURCE,
    START,
    plant_fake,
    plant_series,
)
from plantcraft_sdk.testplant import plant_assets as assets
from plantcraft_sdk.testplant import plant_signals as signals

__all__ = ["APP_KEY", "HOURS", "NOW", "SOURCE", "START", "assets", "make_fake", "signals"]
__all__ += ["plant_series"]


def make_fake(**options) -> FakePlantCraft:
    return plant_fake("alarmcraft", "PlantCraft Alarms", "/alarm/", **options)
