"""Settings, all from the environment, each with a safe default.

Secrets (the app key) are never logged or stored by PlantCraft Alarms.

| Variable | Default | Meaning |
|---|---|---|
| ``PLANTCRAFT_URL`` | ``http://127.0.0.1:8060`` | PlantCraft API v1, as this server reaches it |
| ``PLANTCRAFT_PUBLIC_URL`` | empty (same origin) | PlantCraft as the browser reaches it (sign-in page) |
| ``PLANTCRAFT_APP_KEY`` | empty | App key: the monitor reads the plant and publishes with Alarms' service token |
| ``PLANTCRAFT_APP_KEY_FILE`` | empty | File holding the app key (a Docker secret) |
| ``ALARMCRAFT_DATA_DIR`` | ``var`` | Folder of the SQLite database |
| ``ALARMCRAFT_ROOT_PATH`` | ``/alarm`` | Path prefix of the interface and API |
| ``ALARMCRAFT_MONITOR`` | ``true`` | Evaluate the alarms in the background |
| ``ALARMCRAFT_CYCLE_SECONDS`` | ``10`` | Seconds between two evaluations of every alarm |
| ``ALARMCRAFT_DATA_LAG_SECONDS`` | ``5`` | How far behind now the plant's newest values are read |
"""

from __future__ import annotations

from dataclasses import dataclass

from plantcraft_sdk.server.settings import AppSettings, env_flag, env_number

from alarmcraft import APP_ID


@dataclass
class Settings(AppSettings):
    APP_ID = APP_ID

    root_path: str = "/alarm"
    monitor: bool = True
    cycle_seconds: float = 10.0
    data_lag_seconds: float = 5.0

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            **cls.common(APP_ID, "/alarm"),
            monitor=env_flag("ALARMCRAFT_MONITOR", True),
            cycle_seconds=max(1.0, env_number("ALARMCRAFT_CYCLE_SECONDS", 10.0) or 10.0),
            data_lag_seconds=env_number("ALARMCRAFT_DATA_LAG_SECONDS", 5.0),
        )
