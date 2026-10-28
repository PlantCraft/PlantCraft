"""Settings read from the environment, as the suite's compose file sets them."""

from __future__ import annotations

from alarmcraft.config import Settings


def test_compose_environment(tmp_path, monkeypatch):
    secret = tmp_path / "alarmcraft_app_key"
    secret.write_text("key-from-secret\n", encoding="utf-8")
    monkeypatch.delenv("PLANTCRAFT_APP_KEY", raising=False)
    monkeypatch.setenv("PLANTCRAFT_APP_KEY_FILE", str(secret))
    monkeypatch.setenv("PLANTCRAFT_URL", "http://processcraft:8060")
    monkeypatch.setenv("ALARMCRAFT_ROOT_PATH", "/alarm/")
    monkeypatch.setenv("ALARMCRAFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALARMCRAFT_CYCLE_SECONDS", "0.2")
    monkeypatch.setenv("ALARMCRAFT_DATA_LAG_SECONDS", "-3")
    settings = Settings.from_environment()
    assert settings.app_key == "key-from-secret"
    assert settings.processcraft_url == "http://processcraft:8060"
    assert settings.root_path == "/alarm"
    assert settings.database_path == tmp_path / "data" / "alarmcraft.sqlite3"
    assert settings.cycle_seconds == 1.0  # never faster than once a second
    assert settings.data_lag_seconds == 5.0


def test_defaults(tmp_path, monkeypatch):
    for name in ("PLANTCRAFT_APP_KEY", "PLANTCRAFT_APP_KEY_FILE", "ALARMCRAFT_CYCLE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALARMCRAFT_DATA_DIR", str(tmp_path))
    settings = Settings.from_environment()
    assert settings.app_key == "" and settings.monitor is True
    assert settings.root_path == "/alarm" and settings.cycle_seconds == 10
    (tmp_path / "alarmcraft-app-key").write_text("k", encoding="utf-8")
    assert Settings.from_environment().app_key == "k"
