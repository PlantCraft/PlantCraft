"""Settings read from the environment, as the suite's compose file sets them."""

from __future__ import annotations

from modelcraft.config import Settings


def test_compose_environment(tmp_path, monkeypatch):
    secret = tmp_path / "modelcraft_app_key"
    secret.write_text("key-from-secret\n", encoding="utf-8")
    monkeypatch.delenv("PLANTCRAFT_APP_KEY", raising=False)
    monkeypatch.setenv("PLANTCRAFT_APP_KEY_FILE", str(secret))
    monkeypatch.setenv("PLANTCRAFT_URL", "http://processcraft:8060")
    monkeypatch.setenv("MODELCRAFT_ROOT_PATH", "/model/")
    monkeypatch.setenv("MODELCRAFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("MODELCRAFT_JOBS_DIR", raising=False)
    monkeypatch.delenv("MODELCRAFT_RUNNER", raising=False)
    monkeypatch.setenv("MODELCRAFT_RUN_SECONDS", "-3")
    monkeypatch.setenv("MODELCRAFT_ALLOW_EXTERNAL", "yes")
    settings = Settings.from_environment()
    assert settings.app_key == "key-from-secret"
    assert settings.processcraft_url == "http://processcraft:8060"
    assert settings.root_path == "/model"
    assert settings.database_path == tmp_path / "data" / "modelcraft.sqlite3"
    assert settings.jobs_path == tmp_path / "data" / "jobs" and settings.runner == "suite"
    assert settings.run_seconds == 600 and settings.allow_external is True


def test_defaults(tmp_path, monkeypatch):
    for name in (
        "PLANTCRAFT_APP_KEY",
        "PLANTCRAFT_APP_KEY_FILE",
        "MODELCRAFT_JOBS_DIR",
        "MODELCRAFT_RUNNER",
        "MODELCRAFT_ALLOW_EXTERNAL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODELCRAFT_DATA_DIR", str(tmp_path))
    settings = Settings.from_environment()
    assert settings.app_key == "" and settings.allow_external is False
    assert settings.root_path == "/model" and settings.jobs_path == tmp_path / "jobs"
    assert settings.runner == "suite"
    monkeypatch.setenv("MODELCRAFT_RUNNER", "queue")
    assert Settings.from_environment().runner == "queue"
    monkeypatch.setenv("MODELCRAFT_RUNNER", "anything")
    assert Settings.from_environment().runner == "suite"
    assert settings.check_seconds == 120 and settings.run_workers == 2
    (tmp_path / "modelcraft-app-key").write_text("k", encoding="utf-8")
    assert Settings.from_environment().app_key == "k"
