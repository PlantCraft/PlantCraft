"""Authentication configuration for the FastAPI application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from processcraft.config import env_flag


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    username: str = ""
    password: str = ""
    session_days: int = 7

    @classmethod
    def from_environment(cls) -> "AuthConfig":
        if not env_flag("PLANTCRAFT_BASIC_AUTH_ENABLED"):
            return cls(enabled=False)
        # Usernames are stored in lower case; the admin signs in as any spelling.
        username = os.environ.get("PLANTCRAFT_BASIC_AUTH_USERNAME", "").strip().lower()
        password_file = os.environ.get("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", "").strip()
        if not username:
            raise RuntimeError(
                "PLANTCRAFT_BASIC_AUTH_USERNAME is required when authentication is on."
            )
        if not password_file:
            raise RuntimeError(
                "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE is required when authentication is on."
            )
        path = Path(password_file)
        try:
            password = path.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise RuntimeError(f"Could not read the authentication secret at {path}.") from exc
        if not password:
            raise RuntimeError("The authentication secret is empty.")
        return cls(enabled=True, username=username, password=password)
