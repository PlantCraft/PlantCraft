"""A database from an older release opens: the store's ``MIGRATIONS`` add what it lacks
(``plantcraft_sdk.apptest.upgrade_problems``, PlantCraft scale review E10)."""

from __future__ import annotations

from plantcraft_sdk import apptest

from dashcraft.dashboards.store import DashboardStore


def test_an_older_database_opens(tmp_path):
    assert not apptest.upgrade_problems(DashboardStore, DashboardStore, tmp_path)
