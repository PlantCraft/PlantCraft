"""plantcraft_sdk.client, split into modules by subject (refactor F5), keeps every name it had:
its import path still gives every top-level name of the file before the split, and each class
whose methods moved into mixins still has every method it had. The lists were taken from the
file as it was before its split."""

from __future__ import annotations

import importlib

import pytest

SPLIT = {
    "plantcraft_sdk.client": {
        "names": [
            "BINARY_READS_ENV",
            "BadRequest",
            "DEFAULT_TIMEOUT",
            "DEMO_READS",
            "DemoVisitWrite",
            "ETAG_ENTRIES",
            "ETAG_MAX_BYTES",
            "Forbidden",
            "HISTORIAN_READS_API",
            "HISTORIAN_RETRY_SECONDS",
            "HISTORIAN_URL_ENV",
            "LLM_TIMEOUT",
            "NotFound",
            "PAGE_SIZE",
            "PlantCraftClient",
            "PlantCraftError",
            "RENEW_MARGIN_SECONDS",
            "RETRY_STATUSES",
            "SERIES_TIMEOUT",
            "Unauthorized",
            "Unavailable",
            "_Historian",
            "_demo_visit_write",
            "_error",
            "_expiry",
            "_time",
            "_token_app",
            "error_for",
        ],
        "classes": {
            "PlantCraftClient": [
                "__init__",
                "close",
                "__enter__",
                "__exit__",
                "with_token",
                "_url",
                "_send",
                "_exchange",
                "token",
                "_read",
                "_read_exchange",
                "_all_pages",
                "_historian_serves",
                "keys",
                "service_token",
                "renew_browser_token",
                "me",
                "apps",
                "installation_id",
                "app_license",
                "platform_version",
                "installation_time_zone",
                "features",
                "assets",
                "sync_result_assets",
                "remove_result_assets",
                "asset_types",
                "asset",
                "signals",
                "signal",
                "series",
                "summary",
                "series_runs",
                "series_run_list",
                "lab_samples",
                "series_pandas",
                "series_many",
                "_series_batch",
                "series_many_pandas",
                "series_frame",
                "value",
                "put_series",
                "put_series_runs",
                "retire_series",
                "audit",
                "people",
                "groups",
                "notification_settings",
                "notify",
                "resolve_notification",
                "_for_app",
                "put_results",
                "results",
                "result_history",
                "post_event",
                "put_event_catalog",
                "put_contributions",
                "contributions",
                "llm",
                "put_calendar",
                "put_todo",
                "todos",
                "close_todos",
                "_own",
                "app_settings",
                "explore",
                "event_catalog",
                "post_events",
                "events",
                "put_runs",
                "put_knowledge",
                "delete_knowledge",
                "knowledge",
                "runs",
                "put_schedules",
                "schedules",
                "_put_chunks",
            ],
        },
    },
}


@pytest.mark.parametrize("module", sorted(SPLIT))
def test_split_module_keeps_its_names(module: str) -> None:
    loaded = importlib.import_module(module)
    missing = [name for name in SPLIT[module]["names"] if not hasattr(loaded, name)]
    assert missing == []
    for cls, methods in SPLIT[module]["classes"].items():
        owner = getattr(loaded, cls)
        assert [name for name in methods if not hasattr(owner, name)] == []
