"""A database from an older release opens: each store's ``MIGRATIONS`` add what it lacks
(``plantcraft_sdk.apptest.upgrade_problems``, PlantCraft scale review E10)."""

from __future__ import annotations

import pytest
from plantcraft_sdk import apptest

from linkcraft.catalog.presets import PresetStore
from linkcraft.engine.jobs import JobStore
from linkcraft.loops.store import LoopStore
from linkcraft.signals.store import SignalStore


@pytest.mark.parametrize(
    ("store", "open_store"),
    [
        (PresetStore, PresetStore),
        (JobStore, JobStore),
        (SignalStore, SignalStore),
        (LoopStore, lambda db: LoopStore(db, PresetStore(db))),
    ],
)
def test_an_older_database_opens(tmp_path, store, open_store):
    assert not apptest.upgrade_problems(store, open_store, tmp_path)
