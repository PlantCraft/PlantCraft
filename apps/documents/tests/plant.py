"""The plant tests read: the suite's test plant (``plantcraft_sdk.testplant``: the Simulator's
loops as assets and 12 hours of their signals ending at ``NOW``) served to PlantCraft Documents,
and its four users (admin, engineer, operator, outsider)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from plantcraft_sdk.contributes import contributions
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


MANIFEST = tomllib.loads((Path(__file__).parents[1] / "app.toml").read_text(encoding="utf-8"))


def make_fake(**options) -> FakePlantCraft:
    """The test plant, with what PlantCraft Documents's ``app.toml`` contributes already sent (as the
    app does when it starts): an event, feed, to-do or model use it does not declare is refused."""

    fake = plant_fake("doccraft", "PlantCraft Documents", "/doc/", **options)
    fake.client(None, app="doccraft", key=APP_KEY).put_contributions(contributions(MANIFEST))
    return fake
