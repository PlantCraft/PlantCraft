"""Settings, all from the environment, each with a safe default.

Secrets (the app key) are never logged or stored by View.

| Variable | Default | Meaning |
|---|---|---|
| ``PLANTCRAFT_URL`` | ``http://127.0.0.1:8060`` | PlantCraft API v1, as this server reaches it |
| ``PLANTCRAFT_PUBLIC_URL`` | empty (same origin) | PlantCraft as the browser reaches it (sign-in page) |
| ``PLANTCRAFT_APP_KEY`` | empty | App key: dashboards read plant data with View's service token |
| ``PLANTCRAFT_APP_KEY_FILE`` | empty | File holding the app key (a Docker secret) |
| ``DASHCRAFT_DATA_DIR`` | ``var`` | Folder of the SQLite database |
| ``DASHCRAFT_ROOT_PATH`` | ``/dash`` | Path prefix of the interface and API |
| ``DASHCRAFT_PUBLIC_LINKS`` | ``true`` | Editors may create read-only links that open one dashboard without sign-in |
| ``DASHCRAFT_CACHE_SECONDS`` | ``10`` | How long one read of plant data is shared by every viewer |
| ``DASHCRAFT_REPORT_SECONDS`` | ``30`` | How often the reports due are looked for and sent (0: never) |
"""

from __future__ import annotations

from dataclasses import dataclass

from plantcraft_sdk.server.settings import AppSettings, env_flag, env_number

from dashcraft import APP_ID


@dataclass
class Settings(AppSettings):
    APP_ID = APP_ID

    root_path: str = "/dash"
    public_links: bool = True
    cache_seconds: float = 10.0
    report_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            **cls.common(APP_ID, "/dash"),
            public_links=env_flag("DASHCRAFT_PUBLIC_LINKS", True),
            cache_seconds=env_number("DASHCRAFT_CACHE_SECONDS", 10.0),
            report_seconds=env_number("DASHCRAFT_REPORT_SECONDS", 30.0),
        )
