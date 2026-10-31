"""Analytics' own SQLite database: the suite's store (``plantcraft_sdk.server.store``), with
row times to the second, as Analytics has always written them."""

from __future__ import annotations

from plantcraft_sdk.server import store
from plantcraft_sdk.server.store import Database, Migration, add_columns, recorded_at

__all__ = ["Database", "Migration", "Store", "add_columns", "recorded_at"]


class Store(store.Store):
    TIMESPEC = "seconds"
