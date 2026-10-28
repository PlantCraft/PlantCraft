"""Settings read from the environment, as the suite's compose file sets them."""

from __future__ import annotations

from linkcraft.config import Settings


def test_compose_environment(tmp_path, monkeypatch):
    secret = tmp_path / "linkcraft_app_key"
    secret.write_text("key-from-secret\n", encoding="utf-8")
    monkeypatch.delenv("PLANTCRAFT_APP_KEY", raising=False)
    monkeypatch.setenv("PLANTCRAFT_APP_KEY_FILE", str(secret))
    monkeypatch.setenv("PLANTCRAFT_URL", "http://processcraft:8060")
    monkeypatch.setenv("LINKCRAFT_ROOT_PATH", "/link/")
    monkeypatch.setenv("LINKCRAFT_DATA_DIR", str(tmp_path / "data"))
    settings = Settings.from_environment()
    assert settings.app_key == "key-from-secret"
    assert settings.processcraft_url == "http://processcraft:8060"
    assert settings.root_path == "/link"
    assert settings.database_path == tmp_path / "data" / "linkcraft.sqlite3"


def test_app_key_falls_back_to_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("PLANTCRAFT_APP_KEY", raising=False)
    monkeypatch.delenv("PLANTCRAFT_APP_KEY_FILE", raising=False)
    monkeypatch.setenv("LINKCRAFT_DATA_DIR", str(tmp_path))
    assert Settings.from_environment().app_key == ""
    (tmp_path / "linkcraft-app-key").write_text("k", encoding="utf-8")
    assert Settings.from_environment().app_key == "k"
    monkeypatch.setenv("PLANTCRAFT_APP_KEY", "direct")
    assert Settings.from_environment().app_key == "direct"


def test_a_missing_key_file_means_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("PLANTCRAFT_APP_KEY", raising=False)
    monkeypatch.setenv("PLANTCRAFT_APP_KEY_FILE", str(tmp_path / "absent"))
    monkeypatch.setenv("LINKCRAFT_DATA_DIR", str(tmp_path))
    assert Settings.from_environment().app_key == ""
