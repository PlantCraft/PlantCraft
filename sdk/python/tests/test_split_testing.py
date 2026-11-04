"""plantcraft_sdk.testing, split into modules by subject (refactor F5), keeps every name it had:
its import path still gives every top-level name of the file before the split, and each class
whose methods moved into mixins still has every method it had. The lists were taken from the
file as it was before its split."""

from __future__ import annotations

import importlib

import pytest

SPLIT = {
    "plantcraft_sdk.testing": {
        "names": [
            "BASE_URL",
            "DEFAULT_APPS",
            "DEFAULT_APP_KEYS",
            "DEFAULT_ASSETS",
            "DEFAULT_GROUPS",
            "DEFAULT_SIGNALS",
            "DEFAULT_USERS",
            "FAKE_SOURCE",
            "FakeLinks",
            "FakePlantCraft",
            "FakeResponse",
            "PERMISSIONS_USED",
            "SESSION_COOKIE",
            "_Abort",
            "_CHANGE_FIELDS",
            "_LinksRoutes",
            "_ROUTES",
            "_Request",
            "_SHORT",
            "_TEMPLATES",
            "_TYPED_KINDS",
            "_multi",
            "_signal",
            "_template",
            "synthetic",
            "synthetic_text",
        ],
        "classes": {
            "FakePlantCraft": [
                "__init__",
                "now",
                "data_end",
                "jwks",
                "revoke",
                "end_session",
                "rotate_key",
                "token",
                "_grant",
                "http_client",
                "client",
                "verifier",
                "_given",
                "kind",
                "_signal_payload",
                "_values",
                "handle",
                "_app_refusal",
                "_httpx",
                "app",
                "_caller",
                "_reader",
                "_known",
                "_signal_or_404",
                "_route_keys",
                "_route_revoked",
                "_route_renew",
                "_route_service_token",
                "_route_me",
                "_route_installation",
                "_route_apps",
                "_scope",
                "_signal_in_scope",
                "_route_assets",
                "_app_caller",
                "_route_put_result_assets",
                "_route_remove_result_assets",
                "_route_asset_types",
                "_route_explore",
                "_route_asset",
                "_route_signals",
                "_route_signal",
                "_range",
                "_route_series",
                "_route_series_batch",
                "_extremes",
                "_route_put_series",
                "_runs",
                "_route_run_list",
                "_route_put_series_runs",
                "_route_retire_series",
                "_route_value",
                "_route_audit",
                "_route_people",
                "_route_groups",
                "_route_notification_settings",
                "_route_notify",
                "_route_resolve_notification",
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
