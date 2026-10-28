"""The settings and the PlantCraft connection every app server shares."""

from dataclasses import dataclass

from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.server.settings import (
    AppSettings,
    app_key_from_environment,
    env_flag,
    env_number,
    env_root_path,
)
from plantcraft_sdk.testing import BASE_URL, FakePlantCraft


@dataclass
class Settings(AppSettings):
    APP_ID = "notecraft"

    root_path: str = "/note"
    loud: bool = False

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(**cls.common("notecraft", "/note"), loud=env_flag("NOTECRAFT_LOUD"))


def test_environment_helpers(monkeypatch):
    for value, expected in (("on", True), ("YES", True), ("0", False), ("  ", True)):
        monkeypatch.setenv("X_FLAG", value)
        assert env_flag("X_FLAG", True) is expected
    for value, expected in (("2.5", 2.5), ("-1", 7.0), ("nope", 7.0), ("", 7.0), ("0", 0.0)):
        monkeypatch.setenv("X_NUMBER", value)
        assert env_number("X_NUMBER", 7.0) == expected
    monkeypatch.setenv("X_NUMBER", "0")
    assert env_number("X_NUMBER", 7.0, allow_zero=False) == 7.0
    for value, expected in (("note", "/note"), ("/note/", "/note"), ("/", ""), (" ", "")):
        monkeypatch.setenv("X_ROOT", value)
        assert env_root_path("X_ROOT", "/note") == expected
    monkeypatch.delenv("X_ROOT")
    assert env_root_path("X_ROOT", "/note") == "/note"


def test_app_key_from_the_variable_then_the_named_file_then_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("PLANTCRAFT_APP_KEY", raising=False)
    monkeypatch.delenv("PLANTCRAFT_APP_KEY_FILE", raising=False)
    assert app_key_from_environment("notecraft", tmp_path) == ""
    (tmp_path / "notecraft-app-key").write_text("from-folder\n")
    assert app_key_from_environment("notecraft", tmp_path) == "from-folder"
    secret = tmp_path / "secret"
    secret.write_text(" from-secret ")
    monkeypatch.setenv("PLANTCRAFT_APP_KEY_FILE", str(secret))
    assert app_key_from_environment("notecraft", tmp_path) == "from-secret"
    monkeypatch.setenv("PLANTCRAFT_APP_KEY", "from-env")
    assert app_key_from_environment("notecraft", tmp_path) == "from-env"


def test_app_settings_read_the_common_variables(tmp_path, monkeypatch):
    for name in ("PLANTCRAFT_URL", "PLANTCRAFT_PUBLIC_URL", "PLANTCRAFT_APP_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NOTECRAFT_ROOT_PATH", raising=False)
    monkeypatch.setenv("NOTECRAFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANTCRAFT_APP_KEY", "k")
    monkeypatch.setenv("NOTECRAFT_LOUD", "1")
    settings = Settings.from_environment()
    assert settings.processcraft_url == "http://127.0.0.1:8060"
    assert settings.root_path == "/note" and settings.loud
    assert settings.database_path == tmp_path / "notecraft.sqlite3"
    assert settings.login_url == "/login"
    assert "k" not in repr(settings)
    assert Settings.common("notecraft", "/note", app_key=False)["app_key"] == ""


class Runtime(PlatformRuntime):
    def __init__(self, settings, **clients):
        self.settings = settings
        self.connect("notecraft", settings, **clients)


def test_platform_runtime_connects_and_audits_as_the_person():
    fake = FakePlantCraft()
    settings = Settings(processcraft_url=BASE_URL)
    runtime = Runtime(settings, verifier=fake.verifier("notecraft"), http_client=fake.http_client())
    assert not runtime.has_service_key
    user = runtime.verifier.user(fake.token("ana", apps={"notecraft": "editor"}))
    assert isinstance(runtime.user_client(user), PlantCraftClient)
    runtime.audit(user, "note.saved", "note:1", {"n": 1})
    assert fake.audit_log[-1]["action"] == "notecraft.note.saved"
    runtime.close_platform()
