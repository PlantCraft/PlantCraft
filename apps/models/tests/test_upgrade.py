"""A database from an older release opens: each store's ``MIGRATIONS`` add what it lacks
(``plantcraft_sdk.apptest.upgrade_problems``, PlantCraft scale review E10)."""

from __future__ import annotations

import pytest
from plantcraft_sdk import apptest

from modelcraft.projects.store import ProjectStore
from modelcraft.runs.store import RunStore


@pytest.mark.parametrize("store", [ProjectStore, RunStore])
def test_an_older_database_opens(tmp_path, store):
    assert not apptest.upgrade_problems(store, store, tmp_path)
