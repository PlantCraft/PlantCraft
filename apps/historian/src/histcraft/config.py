"""Settings, from the environment.

Every setting has a safe default. Historian keeps two sets of tables, each with
one writer (docs/boundary.md): the configuration (sources, points, settings,
requests; written by the server) and the archive (archived values, snapshots,
collector state; written by the collector). In a plant both live in one
PostgreSQL database (``HISTCRAFT_DATABASE_URL``); without it, in two SQLite
files of the data folder, ``config.sqlite3`` and ``archive.sqlite3`` (tests,
demos, one-laptop installs).

| Variable | Default | Meaning |
|---|---|---|
| ``PLANTCRAFT_URL`` | ``http://127.0.0.1:8060`` | PlantCraft, as this server reaches it (signing keys) |
| ``PLANTCRAFT_PUBLIC_URL`` | empty (same origin) | PlantCraft as the browser reaches it (sign-in page) |
| ``HISTCRAFT_DATA_DIR`` | ``var`` | Folder of the SQLite databases |
| ``HISTCRAFT_DATABASE_URL`` | empty (SQLite) | PostgreSQL, ``postgresql://user@host:5432/db``, with no password in it |
| ``HISTCRAFT_DATABASE_PASSWORD_FILE`` | empty | File holding the PostgreSQL password (a Docker secret) |
| ``HISTCRAFT_ROOT_PATH`` | ``/hist`` | Path prefix of the interface and API |
| ``HISTCRAFT_COLLECTOR`` | ``embedded`` | ``embedded``: ``histcraft serve`` also collects; ``off``: a separate ``histcraft collect`` does |
| ``HISTCRAFT_FLUSH_SECONDS`` | ``5`` | How often the collector writes archived values (as recent values, one row) and snapshots |
| ``HISTCRAFT_ARCHIVE_SECONDS`` | ``60`` | How often the recent values move into the archive's chunks (reads see them either way) |
| ``HISTCRAFT_CONFIG_SECONDS`` | ``5`` | How often the collector rereads the point configuration and requests |
| ``HISTCRAFT_OPCUA_TIMEOUT`` | ``10`` | Seconds before an OPC UA request is given up |
| ``HISTCRAFT_QUERY_TIMEOUT`` | ``30`` | Seconds a read of series may run in PostgreSQL before it is cancelled (HTTP 504) |
| ``HISTCRAFT_READ_BATCH`` | ``500`` | Nodes per OPC UA Read request |
| ``HISTCRAFT_SECRET_KEY_FILE`` | ``<data dir>/secret.key`` | Key that encrypts source passwords (created 0600 on first use) |
| ``HISTCRAFT_CSV_DIRS`` | ``/csv`` | Folders CSV sources may read (``os.pathsep`` between them), besides ``<data dir>/files`` |
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from plantcraft_sdk.server.settings import AppSettings, env_number, env_text

from histcraft import APP_ID
from histcraft.i18n import t


def positive(name: str, default: float) -> float:
    """A number from the environment above zero; ``default`` otherwise."""

    return env_number(name, default, allow_zero=False)


# Where CSV sources may read (security audit 2026-10-22): the folders in HISTCRAFT_CSV_DIRS
# (``os.pathsep`` between them; ``/csv`` when unset, where the installation mounts
# data/histcraft-csv) and ``files/`` in the data folder (CSVs sent from the Sources page). Any
# other path in the container (its environment in /proc, the key that encrypts source
# passwords) is refused, whoever saved the source.
CSV_DIRS_ENV = "HISTCRAFT_CSV_DIRS"
DEFAULT_CSV_DIRS = "/csv"
UPLOADED_CSV_DIR = "files"


# CSV imports (Import & export): files checked and not confirmed yet in ``pending/``, files
# confirmed and waiting for the collector to write their values as ``<import id>.csv``. Each is
# deleted once its values are archived: only the values are kept.
IMPORTS_DIR = "imports"


def data_folder() -> str:
    """``HISTCRAFT_DATA_DIR`` (default ``var``), for code that has no ``Settings`` at hand."""

    return os.environ.get("HISTCRAFT_DATA_DIR", "var").strip() or "var"


def csv_folders() -> list[Path]:
    """The folders CSV sources may read, resolved."""

    names = os.environ.get(CSV_DIRS_ENV, DEFAULT_CSV_DIRS).split(os.pathsep)
    folders = [Path(name.strip()).expanduser() for name in names if name.strip()]
    folders.append(Path(data_folder()) / UPLOADED_CSV_DIR)
    return [folder.resolve() for folder in folders]


def csv_path_allowed(path: str | Path) -> bool:
    """Whether a CSV source may read ``path``: inside one of ``csv_folders`` once links are
    followed."""

    resolved = Path(path).expanduser().resolve()
    return any(folder in resolved.parents for folder in csv_folders())


def csv_pattern_allowed(pattern: str) -> bool:
    """Whether a CSV source may read ``pattern``: a file, or a pattern in its last part only
    (``/csv/lims/*.csv``), in one of ``csv_folders``."""

    path = Path(pattern).expanduser()
    if any(ch in part for part in path.parts[:-1] for ch in "*?["):
        return False
    return csv_path_allowed(path.parent / "file" if any(ch in path.name for ch in "*?[") else path)


def outside_csv_folders() -> str:
    """What a CSV source with a path elsewhere is told."""

    return t(
        "A CSV source reads only files in {folders}.",
        folders=", ".join(str(folder) for folder in csv_folders()),
    )


@dataclass
class Settings(AppSettings):
    APP_ID = APP_ID

    root_path: str = "/hist"
    collector: str = "embedded"
    flush_seconds: float = 5.0
    # How often the recent values move into chunks (``ArchiveStore.settle``).
    archive_seconds: float = 60.0
    config_seconds: float = 5.0
    opcua_timeout: float = 10.0
    # Seconds a read of series may run in PostgreSQL before it is cancelled (504).
    query_timeout: float = 30.0
    # Values the series answers in flight may hold together (api/read_budget.py), shared by
    # the server's processes (``HISTCRAFT_WORKERS``): each holds its part.
    read_values: int = 4_000_000
    read_batch: int = 500
    # How long recent reads of ``source``-mode signals are kept in memory (0: off).
    source_cache_seconds: float = 300.0
    secret_key_file: str = ""
    database_url: str = ""
    database_password_file: str = ""
    # The gateway (Telegraf) pushes MQTT, Modbus and SQL values to the collector on this port
    # (0: no gateway), at this address as the gateway reaches it.
    ingest_port: int = 0
    ingest_url: str = "http://histcraft-collector:8186"

    def database_password(self) -> str:
        """The PostgreSQL password, read from its file when needed (never kept)."""

        if not self.database_password_file:
            return ""
        try:
            return Path(self.database_password_file).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @property
    def secret_key_path(self) -> Path:
        """The key that encrypts source passwords (never in the database)."""

        return Path(self.secret_key_file) if self.secret_key_file else self.data_dir / "secret.key"

    @property
    def config_target(self) -> str | Path:
        """Where the configuration lives: the PostgreSQL URL, or its SQLite file."""

        return self.database_url or self.data_dir / "config.sqlite3"

    @property
    def archive_target(self) -> str | Path:
        return self.database_url or self.data_dir / "archive.sqlite3"

    @classmethod
    def from_environment(cls) -> Settings:
        collector = env_text("HISTCRAFT_COLLECTOR", "embedded").lower()
        return cls(
            # No app key: the Historian answers PlantCraft and the apps, it never calls them
            # with a service token.
            **cls.common(APP_ID, "/hist", app_key=False),
            collector="off" if collector in {"off", "0", "false", "no"} else "embedded",
            flush_seconds=positive("HISTCRAFT_FLUSH_SECONDS", 5.0),
            archive_seconds=positive("HISTCRAFT_ARCHIVE_SECONDS", 60.0),
            config_seconds=positive("HISTCRAFT_CONFIG_SECONDS", 5.0),
            opcua_timeout=positive("HISTCRAFT_OPCUA_TIMEOUT", 10.0),
            query_timeout=positive("HISTCRAFT_QUERY_TIMEOUT", 30.0),
            read_values=int(
                positive("HISTCRAFT_READ_VALUES", 4_000_000)
                // max(1, int(positive("HISTCRAFT_SERVER_PROCESSES", 1)))
            ),
            read_batch=int(positive("HISTCRAFT_READ_BATCH", 500)),
            source_cache_seconds=positive("HISTCRAFT_SOURCE_CACHE_SECONDS", 300.0),
            secret_key_file=env_text("HISTCRAFT_SECRET_KEY_FILE"),
            database_url=env_text("HISTCRAFT_DATABASE_URL"),
            database_password_file=env_text("HISTCRAFT_DATABASE_PASSWORD_FILE"),
            ingest_port=int(env_text("HISTCRAFT_INGEST_PORT", "0") or 0),
            ingest_url=env_text("HISTCRAFT_INGEST_URL", "http://histcraft-collector:8186"),
        )
