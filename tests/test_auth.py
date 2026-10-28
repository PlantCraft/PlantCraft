from __future__ import annotations

import pytest

from processcraft.auth.config import AuthConfig


def test_disabled_authentication_requires_no_credentials(monkeypatch) -> None:
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)

    assert AuthConfig.from_environment() == AuthConfig(enabled=False)


def test_environment_reads_password_from_file(monkeypatch, tmp_path) -> None:
    secret = tmp_path / "password"
    secret.write_text("senha-forte\n", encoding="utf-8")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "engenharia")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))

    config = AuthConfig.from_environment()

    assert config.enabled is True
    assert config.username == "engenharia"
    assert config.password == "senha-forte"


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        (
            {
                "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
                "PLANTCRAFT_BASIC_AUTH_USERNAME": "",
                "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": "/nao-importa",
            },
            "PLANTCRAFT_BASIC_AUTH_USERNAME",
        ),
        (
            {
                "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
                "PLANTCRAFT_BASIC_AUTH_USERNAME": "cpm",
                "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": "",
            },
            "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE",
        ),
        (
            {
                "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
                "PLANTCRAFT_BASIC_AUTH_USERNAME": "cpm",
                "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": "/arquivo/inexistente",
            },
            "Could not read the authentication secret",
        ),
    ],
)
def test_enabled_authentication_fails_closed(
    monkeypatch,
    environment: dict[str, str],
    message: str,
) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=message):
        AuthConfig.from_environment()
