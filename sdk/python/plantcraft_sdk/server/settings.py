"""The settings every app reads from the environment, written once.

Each app's ``Settings`` is a dataclass that extends ``AppSettings`` with its own fields, and reads
the common ones with ``AppSettings.common``::

    @dataclass
    class Settings(AppSettings):
        root_path: str = "/alarm"
        monitor: bool = True

        @classmethod
        def from_environment(cls) -> Settings:
            return cls(
                **cls.common("alarmcraft", "/alarm"),
                monitor=env_flag("ALARMCRAFT_MONITOR", True),
            )

The common settings (``docs/app-standard.md``, section 6):

| Variable | Default | Meaning |
|---|---|---|
| ``PLANTCRAFT_URL`` | ``http://127.0.0.1:8060`` | PlantCraft API v1, as this server reaches it |
| ``PLANTCRAFT_PUBLIC_URL`` | empty (same origin) | PlantCraft as the browser reaches it (sign-in page) |
| ``PLANTCRAFT_APP_KEY`` | empty | The app's key: its service token for background work |
| ``PLANTCRAFT_APP_KEY_FILE`` | empty | File holding the app key (a Docker secret) |
| ``<APP>_DATA_DIR`` | ``var`` | The app's data folder (its SQLite database) |
| ``<APP>_ROOT_PATH`` | the app's prefix | Path prefix of the interface and API |

Secrets (the app key) are never logged: ``app_key`` stays out of the dataclass ``repr``.
Standard library only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PLANTCRAFT_URL = "http://127.0.0.1:8060"


def env_flag(name: str, default: bool = False) -> bool:
    """An on/off environment setting: 1, true, yes or on (any case) mean on."""

    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_number(name: str, default: float, *, allow_zero: bool = True) -> float:
    """A number from the environment; ``default`` when unset, unreadable or negative (or zero,
    with ``allow_zero=False``)."""

    try:
        value = float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    if value < 0 or (value == 0 and not allow_zero):
        return default
    return value


def env_text(name: str, default: str = "") -> str:
    """A text setting, stripped; ``default`` when unset or blank."""

    return os.environ.get(name, "").strip() or default


def env_root_path(name: str, default: str) -> str:
    """A path prefix: ``/alarm`` from ``alarm``, ``/alarm/`` or ``/alarm``; empty for ``/``."""

    root = "/" + os.environ.get(name, default).strip().strip("/")
    return "" if root == "/" else root


def app_key_from_environment(app_id: str, data_dir: Path) -> str:
    """The app key: ``PLANTCRAFT_APP_KEY``, else the file ``PLANTCRAFT_APP_KEY_FILE`` names
    (a Docker secret in the suite's compose file), else ``<data dir>/<app id>-app-key``."""

    value = os.environ.get("PLANTCRAFT_APP_KEY", "").strip()
    if value:
        return value
    named = os.environ.get("PLANTCRAFT_APP_KEY_FILE", "").strip()
    path = Path(named).expanduser() if named else data_dir / f"{app_id}-app-key"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass
class AppSettings:
    """What every app's settings hold. Subclasses add their own fields (all with defaults) and
    may redeclare ``root_path`` with their prefix as its default."""

    APP_ID = ""

    processcraft_url: str = DEFAULT_PLANTCRAFT_URL
    processcraft_public_url: str = ""
    app_key: str = field(default="", repr=False)
    data_dir: Path = Path("var")
    root_path: str = ""

    @property
    def database_path(self) -> Path:
        """The app's SQLite file, ``<data dir>/<app id>.sqlite3``."""

        return self.data_dir / f"{self.APP_ID}.sqlite3"

    @property
    def login_url(self) -> str:
        return f"{self.processcraft_public_url.rstrip('/')}/login"

    @staticmethod
    def common(app_id: str, root_path: str, *, app_key: bool = True) -> dict[str, Any]:
        """The common settings from the environment, as keyword arguments for the dataclass.
        ``app_key=False`` for an app that has no service token (it is then left empty)."""

        prefix = app_id.upper()
        data_dir = Path(env_text(f"{prefix}_DATA_DIR", "var")).expanduser()
        return {
            "processcraft_url": env_text("PLANTCRAFT_URL", DEFAULT_PLANTCRAFT_URL),
            "processcraft_public_url": env_text("PLANTCRAFT_PUBLIC_URL"),
            "app_key": app_key_from_environment(app_id, data_dir) if app_key else "",
            "data_dir": data_dir,
            "root_path": env_root_path(f"{prefix}_ROOT_PATH", root_path),
        }
