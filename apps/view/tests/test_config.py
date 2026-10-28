"""Settings read from the environment, as the suite's compose file sets them."""

from __future__ import annotations

from dashcraft.config import Settings


def test_compose_environment(tmp_path, monkeypatch):
    secret = tmp_path / "dashcraft_app_key"
    secret.write_text("key-from-secret\n", encoding="utf-8")
    monkeypatch.delenv("PLANTCRAFT_APP_KEY", raising=False)
    monkeypatch.setenv("PLANTCRAFT_APP_KEY_FILE", str(secret))
    monkeypatch.setenv("PLANTCRAFT_URL", "http://processcraft:8060")
    monkeypatch.setenv("DASHCRAFT_ROOT_PATH", "/dash/")
    monkeypatch.setenv("DASHCRAFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DASHCRAFT_PUBLIC_LINKS", "false")
    monkeypatch.setenv("DASHCRAFT_CACHE_SECONDS", "0")
    settings = Settings.from_environment()
    assert settings.app_key == "key-from-secret"
    assert settings.processcraft_url == "http://processcraft:8060"
    assert settings.root_path == "/dash"
    assert settings.database_path == tmp_path / "data" / "dashcraft.sqlite3"
    assert settings.public_links is False and settings.cache_seconds == 0


def test_defaults(tmp_path, monkeypatch):
    for name in ("PLANTCRAFT_APP_KEY", "PLANTCRAFT_APP_KEY_FILE", "DASHCRAFT_PUBLIC_LINKS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DASHCRAFT_DATA_DIR", str(tmp_path))
    settings = Settings.from_environment()
    assert settings.app_key == "" and settings.public_links is True
    assert settings.root_path == "/dash" and settings.cache_seconds == 10
    (tmp_path / "dashcraft-app-key").write_text("k", encoding="utf-8")
    assert Settings.from_environment().app_key == "k"
