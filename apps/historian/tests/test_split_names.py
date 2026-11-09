"""Files split into modules by subject (PlantCraft refactor F5) keep every name they had: each
old import path still gives every top-level name of the file before the split, and each class
split into parts still has every method it had. The lists were taken from the files before their
split."""

from __future__ import annotations

import importlib

import pytest

SPLIT = {
    "histcraft.collector.service": {
        "names": [
            "LOGGER",
            "COMPACT_SECONDS",
            "TOTALS_SECONDS",
            "COMPACT_AGE_MS",
            "COUNT_SECONDS",
            "LAKE_SECONDS",
            "REQUEST_WINDOW_MS",
            "MAX_BACKOFF",
            "TEXT_READS",
            "TEXT_BACKFILL_HOURS",
            "LEASE_RETRY_SECONDS",
            "GATEWAY_STALE_SECONDS",
            "SUBSCRIPTION_CHECK_SECONDS",
            "SPARKPLUG_TICK",
            "SEEN_LIMIT",
            "HELD_LIMIT",
            "PointState",
            "_compressor",
            "_text",
            "_identity",
            "Collector",
            "CollectorThread",
            "_births_detail",
            "_pushed_value",
            "_describe",
            "source_password",
        ],
        "classes": {
            "Collector": [
                "__init__",
                "_reader_for",
                "calculated",
                "password",
                "_reader",
                "reload",
                "heal_kinds",
                "_source_points",
                "_signature",
                "_write",
                "_hold",
                "_write_held",
                "save_held",
                "flush",
                "_measure_buffer",
                "_note_changes",
                "housekeeping",
                "forecast",
                "suggest_ranges",
                "count_totals",
                "_start_imports",
                "feed_lake",
                "_housekeep",
                "answer_requests",
                "_answer",
                "_backfill",
                "_run_backfill",
                "_answer_csv",
                "_answer_history",
                "_source_task",
                "_watch_csv",
                "_take_csv",
                "_poll",
                "_monitor",
                "_take_held_values",
                "_scan",
                "_sync_tasks",
                "_listen",
                "take_sparkplug",
                "_seed",
                "_add_born",
                "_answer_sparkplug",
                "_ingest_server",
                "ingest",
                "_laboratory",
                "check_gateway",
                "_write_gateway_config",
                "_answer_gateway",
                "_take_lease",
                "run",
                "_flush_or_hold",
                "_collect",
            ]
        },
    },
}


@pytest.mark.parametrize("module", sorted(SPLIT))
def test_a_split_module_keeps_its_names(module: str) -> None:
    loaded = importlib.import_module(module)
    names = SPLIT[module]
    assert [name for name in names["names"] if not hasattr(loaded, name)] == []
    for cls, methods in names["classes"].items():
        assert [method for method in methods if not hasattr(getattr(loaded, cls), method)] == []
