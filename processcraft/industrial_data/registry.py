"""Every data source of an installation, and the reads routed to the one that owns a tag.

The scenario file declares the primary source; it stays read-only here. People
add more sources at runtime (OPC UA, PI Web API, CSV); they live in the
database (``SourceStore``), with any typed password encrypted by a key kept
beside the database file.

A signal of an added source is routed to it once it is used (``signal_routes``:
tag → source). ``RoutingSource`` is the ``DataSource`` the platform reads
through: a read whose tags are all on the primary source goes straight to it,
unchanged; otherwise each source reads its own tags and the frames are joined.
"""

from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from processcraft.config import DataSourceConfig
from processcraft.db import Database, Store
from processcraft.i18n import t
from processcraft.industrial_data.cache import build_cached_source
from processcraft.industrial_data.service import IndustrialData
from processcraft.industrial_data.sources import DataSource, SignalInfo, build_source

PRIMARY = "scenario"
SOURCE_TYPES = {"opcua": "OPC UA", "pi_web_api": "PI Web API", "csv": "CSV file"}
# The connection fields a person may set on an added source, per type.
EDITABLE = {
    "opcua": (
        "endpoint_url",
        "namespace_uri",
        "auth_type",
        "username",
        "password_env",
        "timeout_seconds",
    ),
    "pi_web_api": (
        "base_url",
        "server",
        "auth_type",
        "username",
        "password_env",
        "verify_ssl",
        "ca_bundle",
        "read_mode",
        "timeout_seconds",
        "tags",
    ),
    "csv": ("path",),
}
COMMON = ("timezone", "history_cache_hours")
# An added source that could not be browsed for its signals' kinds is tried again after this.
KINDS_RETRY_SECONDS = 60
_SLUG = re.compile(r"[^a-z0-9]+")


def source_id_for(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return _SLUG.sub("-", plain).strip("-")[:48] or "fonte"


ROUTES_SECONDS = 1.0


class SecretBox:
    """Encrypts the passwords of added sources with a key file beside the database."""

    def __init__(self, path: Path):
        self.path = path
        self._fernet: Any = None

    def _box(self) -> Any:
        if self._fernet is None:
            from cryptography.fernet import Fernet

            try:
                key = self.path.read_bytes().strip()
            except OSError:
                key = b""
            if not key:
                key = Fernet.generate_key()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_bytes(key)
                try:
                    self.path.chmod(0o600)
                except OSError:
                    pass
            self._fernet = Fernet(key)
        return self._fernet

    def seal(self, text: str) -> str:
        return self._box().encrypt(text.encode()).decode() if text else ""

    def open(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._box().decrypt(token.encode()).decode()
        except Exception:  # a lost key file: the password must be typed again
            return ""


class SourceStore(Store):
    """Added sources and the routes of the signals the platform uses."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS data_sources (
        source_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        settings_json TEXT NOT NULL,
        secret TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS signal_routes (
        tag TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        path TEXT NOT NULL DEFAULT '',
        monitored INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_signal_routes_source ON signal_routes(source_id);
    """

    # Writes this process made (the route maps re-read the registry at once after one).
    writes = 0

    @contextmanager
    def _write(self) -> Iterator[Any]:
        try:
            with super()._write() as connection:
                yield connection
        finally:
            self.writes += 1

    def signature(self) -> tuple[Any, ...]:
        """Changes whenever a source or a route is added, edited or removed."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT (SELECT COUNT(*) FROM data_sources), (SELECT MAX(updated_at) FROM data_sources),
                       (SELECT COUNT(*) FROM signal_routes), (SELECT MAX(updated_at) FROM signal_routes),
                       (SELECT TOTAL(monitored) FROM signal_routes)
                """
            ).fetchone()
        return tuple(row)

    def sources(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM data_sources ORDER BY created_at, source_id"
            ).fetchall()
        return [self._row_with_json(row, {"settings": ("settings_json", {})}) for row in rows]

    def source(self, source_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM data_sources WHERE source_id = ?", (source_id,)
            ).fetchone()
        return self._row_with_json(row, {"settings": ("settings_json", {})}) if row else None

    def save_source(
        self,
        source_id: str,
        *,
        name: str,
        type: str,
        settings: dict[str, Any],
        secret: str | None,
        actor: str,
    ) -> None:
        """``secret=None`` keeps the stored password; an empty string clears it."""

        now = self._now()
        with self._lock, self._write() as connection:
            existing = connection.execute(
                "SELECT secret FROM data_sources WHERE source_id = ?", (source_id,)
            ).fetchone()
            kept = existing["secret"] if existing is not None and secret is None else (secret or "")
            connection.execute(
                """
                INSERT INTO data_sources (source_id, name, type, settings_json, secret, created_at, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    name = excluded.name, type = excluded.type, settings_json = excluded.settings_json,
                    secret = excluded.secret, updated_at = excluded.updated_at, updated_by = excluded.updated_by
                """,
                (source_id, name, type, self._json(settings), kept, now, now, actor),
            )

    def delete_source(self, source_id: str) -> int:
        """Remove a source and its routes; returns how many routes went with it."""

        with self._lock, self._write() as connection:
            removed = connection.execute(
                "DELETE FROM signal_routes WHERE source_id = ?", (source_id,)
            ).rowcount
            connection.execute("DELETE FROM data_sources WHERE source_id = ?", (source_id,))
        return removed

    def routes(self, *, source_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            if source_id is None:
                rows = connection.execute("SELECT * FROM signal_routes ORDER BY tag").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM signal_routes WHERE source_id = ? ORDER BY tag", (source_id,)
                ).fetchall()
        return [{**dict(row), "monitored": bool(row["monitored"])} for row in rows]

    def save_routes(self, rows: list[dict[str, Any]]) -> None:
        """Create or update routes; a field left out (``None``) keeps its stored value."""

        now = self._now()
        with self._lock, self._write() as connection:
            for item in rows:
                current = connection.execute(
                    "SELECT * FROM signal_routes WHERE tag = ?", (item["tag"],)
                ).fetchone()
                base = (
                    dict(current)
                    if current
                    else {"name": "", "unit": "", "path": "", "monitored": 0}
                )
                values = {
                    key: base[key] if item.get(key) is None else item[key]
                    for key in ("name", "unit", "path", "monitored")
                }
                connection.execute(
                    """
                    INSERT INTO signal_routes (tag, source_id, name, unit, path, monitored, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tag) DO UPDATE SET
                        source_id = excluded.source_id, name = excluded.name, unit = excluded.unit,
                        path = excluded.path, monitored = excluded.monitored, updated_at = excluded.updated_at
                    """,
                    (
                        item["tag"],
                        item["source_id"],
                        str(values["name"] or ""),
                        str(values["unit"] or ""),
                        str(values["path"] or ""),
                        int(bool(values["monitored"])),
                        now,
                        now,
                    ),
                )

    def delete_routes(self, tags: list[str]) -> None:
        with self._lock, self._write() as connection:
            connection.executemany(
                "DELETE FROM signal_routes WHERE tag = ?", [(tag,) for tag in tags]
            )


class SourceRegistry:
    """The primary source and the added ones: settings, status, browsing and routing."""

    def __init__(self, db: Database, primary_config: DataSourceConfig, primary: DataSource):
        self.store = SourceStore(db)
        self.db = db
        self.primary_config = primary_config
        self.primary = primary
        self.secrets = SecretBox(
            Path(os.environ.get("PLANTCRAFT_SOURCES_KEY_FILE") or db.path.with_name("sources.key"))
        )
        self._lock = threading.Lock()
        self._built: dict[str, tuple[str, IndustrialData]] = {}
        # (signature, foreign, routes, this process's writes, when checked).
        self._routes: (
            tuple[tuple[Any, ...], dict[str, str], dict[str, dict[str, Any]], int, float] | None
        ) = None
        # Per added source: (version, when, tag -> "text" | "number", or None when unreachable).
        self._kinds: dict[str, tuple[str, float, dict[str, str] | None]] = {}
        self.router = RoutingSource(self)
        self.primary_data = IndustrialData(primary_config, self.router)

    # Sources ---------------------------------------------------------------

    def is_added(self, source_id: str) -> bool:
        return source_id != PRIMARY and self.store.source(source_id) is not None

    def known(self, source_id: str) -> bool:
        return source_id == PRIMARY or self.is_added(source_id)

    def list(self) -> list[dict[str, Any]]:
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for route in self.store.routes():
            counts[route["source_id"]][0] += 1
            counts[route["source_id"]][1] += int(route["monitored"])
        items = [self._public_primary(counts[PRIMARY])]
        items.extend(self._public(row, counts[row["source_id"]]) for row in self.store.sources())
        return items

    def get(self, source_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list() if item["source_id"] == source_id), None)

    def _public_primary(self, counts: list[int]) -> dict[str, Any]:
        config = self.primary_config
        return {
            "source_id": PRIMARY,
            "name": t("Scenario source"),
            "type": config.type,
            "type_label": t(SOURCE_TYPES.get(config.type, config.type)),
            "origin": "scenario",
            "read_only": True,
            "endpoint": _endpoint(config),
            "settings": _settings(config),
            "has_password": bool(config.password_env),
            "configured_tags": len(config.tags),
            "routed_signals": counts[0],
            "monitored_signals": counts[1] + len(config.tags),
            "updated_at": None,
            "updated_by": None,
        }

    def _public(self, row: dict[str, Any], counts: list[int]) -> dict[str, Any]:
        settings = dict(row["settings"])
        try:
            config = self._config(row, with_secret=False)
            endpoint = _endpoint(config)
        except (ValidationError, ValueError):
            endpoint = None
        return {
            "source_id": row["source_id"],
            "name": row["name"],
            "type": row["type"],
            "type_label": t(SOURCE_TYPES.get(row["type"], row["type"])),
            "origin": "added",
            "read_only": False,
            "endpoint": endpoint,
            "settings": settings,
            "has_password": bool(row.get("secret")),
            "configured_tags": len(settings.get("tags") or []),
            "routed_signals": counts[0],
            "monitored_signals": counts[1],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    def validate(
        self, type: str, settings: dict[str, Any], password: str | None = None
    ) -> DataSourceConfig:
        """The connection settings as a source configuration; raises ``ValueError`` worded for people."""

        if type not in EDITABLE:
            raise ValueError(t("Unsupported source type: {type}.", type=type))
        allowed = set(EDITABLE[type]) | set(COMMON)
        clean = {
            key: value
            for key, value in settings.items()
            if key in allowed and value not in (None, "")
        }
        clean.setdefault("timezone", self.primary_config.timezone)
        if type == "opcua":
            clean.setdefault("auth_type", "anonymous")
        if type == "pi_web_api" and isinstance(clean.get("tags"), str):
            clean["tags"] = [line.strip() for line in clean["tags"].splitlines() if line.strip()]
        try:
            return DataSourceConfig.model_validate(
                {**clean, "type": type, "password": password or None},
                context={"added_source": True},
            )
        except ValidationError as exc:
            messages = [
                str(error.get("msg", "")).removeprefix("Value error, ") for error in exc.errors()
            ]
            raise ValueError("; ".join(messages) or t("Invalid settings.")) from exc

    def save(
        self,
        source_id: str | None,
        *,
        name: str,
        type: str,
        settings: dict[str, Any],
        password: str | None,
        actor: str,
    ) -> dict[str, Any]:
        """Create (``source_id=None`` or new) or update an added source; ``password=None`` keeps it."""

        name = name.strip()
        if not name:
            raise ValueError(t("Give the source a name."))
        config = self.validate(type, settings, password)
        source_id = (source_id or source_id_for(name)).strip()
        if source_id == PRIMARY:
            raise ValueError(
                t("The scenario's source is set in the scenario file and cannot be changed here.")
            )
        stored = config.model_dump(mode="json", include=set(EDITABLE[type]) | set(COMMON))
        if password is None:
            row = self.store.source(source_id)
            if row and row.get("secret"):
                self._secret_follows(row, type, config)
        secret = None if password is None else self.secrets.seal(password)
        self.store.save_source(
            source_id, name=name, type=type, settings=stored, secret=secret, actor=actor
        )
        with self._lock:
            self._built.pop(source_id, None)
        return self.get(source_id) or {}

    @staticmethod
    def _secret_follows(row: dict[str, Any], type: str, config: DataSourceConfig) -> None:
        """A saved password is only sent to the server and user it was typed for: a new address
        or user asks for it again (``ValueError``), so it never reaches another server."""

        def target(kind: str, settings: dict[str, Any]) -> tuple[str, str, str]:
            url = str(settings.get("endpoint_url") or settings.get("base_url") or "")
            return kind, url.strip().rstrip("/"), str(settings.get("username") or "").strip()

        wanted = config.model_dump(mode="json", include={"endpoint_url", "base_url", "username"})
        if target(row["type"], row["settings"]) != target(type, wanted):
            raise ValueError(
                t(
                    "The server changed: type the password again, so the saved one is never "
                    "sent to another server."
                )
            )

    def remove(self, source_id: str) -> int:
        if source_id == PRIMARY:
            raise ValueError(t("The scenario's source cannot be removed."))
        with self._lock:
            built = self._built.pop(source_id, None)
            self._kinds.pop(source_id, None)
        if built is not None:
            _close(built[1].source)
        return self.store.delete_source(source_id)

    def _config(self, row: dict[str, Any], *, with_secret: bool = True) -> DataSourceConfig:
        settings = dict(row["settings"])
        routed = [item["tag"] for item in self.store.routes(source_id=row["source_id"])]
        settings["tags"] = list(dict.fromkeys([*(settings.get("tags") or []), *routed]))
        password = self.secrets.open(row.get("secret") or "") if with_secret else None
        return self.validate(row["type"], settings, password)

    def data(self, source_id: str) -> IndustrialData:
        """Status, signals and history of one source (the primary one included)."""

        if source_id == PRIMARY:
            return self.primary_data
        row = self.store.source(source_id)
        if row is None:
            raise KeyError(source_id)
        version = f"{row['updated_at']}|{len(self.store.routes(source_id=source_id))}"
        with self._lock:
            built = self._built.get(source_id)
            if built is not None and built[0] == version:
                return built[1]
        config = self._config(row)
        data = IndustrialData(config, build_cached_source(config, self.db))
        with self._lock:
            old = self._built.get(source_id)
            self._built[source_id] = (version, data)
        if old is not None and old[1] is not data:
            _close(old[1].source)
        return data

    def signal_kinds(self, source_id: str) -> dict[str, str]:
        """Tag → ``"text"`` or ``"number"`` as an added source reports its signals.

        The source is browsed once and the answer kept until its settings or routes change;
        an unreachable source gives ``{}`` (its signals read as numbers) and is tried again
        after ``KINDS_RETRY_SECONDS``.
        """

        row = self.store.source(source_id) if source_id != PRIMARY else None
        if row is None:
            return {}
        version = f"{row['updated_at']}|{len(self.store.routes(source_id=source_id))}"
        with self._lock:
            cached = self._kinds.get(source_id)
        if (
            cached is not None
            and cached[0] == version
            and (cached[2] is not None or time.monotonic() - cached[1] < KINDS_RETRY_SECONDS)
        ):
            return cached[2] or {}
        try:
            kinds: dict[str, str] | None = {
                item["tag"]: "text"
                if str(item.get("data_type") or "").lower() in {"text", "string", "str"}
                else "number"
                for item in self.data(source_id).signals()
            }
        except Exception:  # an unreachable source must not hide its signals
            kinds = None
        with self._lock:
            self._kinds[source_id] = (version, time.monotonic(), kinds)
        return kinds or {}

    def test(
        self,
        type: str,
        settings: dict[str, Any],
        password: str | None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Try a connection before saving it; an empty password reuses the stored one."""

        try:
            config = self.validate(type, settings, password)
            if password is None and source_id:
                row = self.store.source(source_id)
                if row and row.get("secret"):
                    self._secret_follows(row, type, config)
                    password = self.secrets.open(row["secret"])
                    config = self.validate(type, settings, password)
        except ValueError as exc:
            return {"ok": False, "message": str(exc), "latency_ms": 0}
        source = build_source(config)
        try:
            return IndustrialData(config, source).status(refresh=True)
        finally:
            _close(source)

    # Routes ----------------------------------------------------------------

    def _route_maps(self) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        # One read of the registry's signature per second at most (scale review E14: a tag at a
        # time, 50,000 signals took 40 s); a write in this process re-reads it at once, another
        # worker's within ROUTES_SECONDS.
        cached = self._routes
        now = time.monotonic()
        writes = self.store.writes
        if cached is not None and cached[3] == writes and now - cached[4] < ROUTES_SECONDS:
            return cached[1], cached[2]
        signature = self.store.signature()
        if cached is None or cached[0] != signature:
            added = {row["source_id"] for row in self.store.sources()}
            routes = {item["tag"]: item for item in self.store.routes()}
            foreign = {
                tag: item["source_id"] for tag, item in routes.items() if item["source_id"] in added
            }
            cached = (signature, foreign, routes, writes, now)
        else:
            cached = (*cached[:3], writes, now)
        self._routes = cached
        return cached[1], cached[2]

    def foreign_routes(self) -> dict[str, str]:
        """Tag → added source, for the tags that are not read from the primary source."""

        return self._route_maps()[0]

    def routes(self) -> dict[str, dict[str, Any]]:
        return self._route_maps()[1]

    def source_of(self, tag: str) -> str:
        return self.foreign_routes().get(tag, PRIMARY)

    def monitored_tags(self) -> list[str]:
        """Tags people chose to use in the platform, beyond the scenario's configured ones."""

        return [
            tag
            for tag, item in self.routes().items()
            if item["monitored"] and self.known(item["source_id"])
        ]

    def routed_signals(self) -> list[dict[str, Any]]:
        """Signal metadata stored with the routes (name, unit, the source's folder)."""

        return [
            {
                "tag": tag,
                "name": item["name"] or tag,
                "asset": item["path"],
                "unit": item["unit"],
                "description": "",
                "source_id": item["source_id"],
            }
            for tag, item in self.routes().items()
        ]

    def use(self, source_id: str, signals: list[dict[str, Any]], *, monitored: bool | None) -> int:
        """Route these signals to ``source_id``; ``monitored`` adds them to (or takes them from) the platform."""

        if not self.known(source_id):
            raise ValueError(t("Unknown source: {source}.", source=source_id))
        rows = [
            {
                "tag": str(item["tag"]),
                "source_id": source_id,
                "name": item.get("name"),
                "unit": item.get("unit"),
                "path": item.get("asset") if item.get("asset") is not None else item.get("path"),
                "monitored": monitored,
            }
            for item in signals
            if item.get("tag")
        ]
        self.store.save_routes(rows)
        return len(rows)

    def forget(self, tags: list[str]) -> None:
        self.store.delete_routes(tags)


class RoutingSource:
    """The ``DataSource`` the platform reads: each tag from the source that owns it."""

    def __init__(self, registry: SourceRegistry):
        self.registry = registry
        self._failed: list[tuple[str, str]] | None = None
        self._from_cache: bool | None = None

    @property
    def primary(self) -> DataSource:
        return self.registry.primary

    def __getattr__(self, name: str) -> Any:
        # Anything else (the cache, the PI session) is the primary source's.
        if name in {"registry", "_failed", "_from_cache"}:
            raise AttributeError(name)
        return getattr(self.registry.primary, name)

    @property
    def failed_tags(self) -> list[tuple[str, str]]:
        if self._failed is None:
            return getattr(self.primary, "failed_tags", [])
        return self._failed

    @failed_tags.setter
    def failed_tags(self, value: list[tuple[str, str]]) -> None:
        self._failed = value

    @property
    def last_read_from_cache(self) -> bool:
        if self._from_cache is None:
            return bool(getattr(self.primary, "last_read_from_cache", False))
        return self._from_cache

    def list_signals(self) -> list[SignalInfo]:
        return self.primary.list_signals()

    def test_connection(self) -> str | None:
        return self.primary.test_connection()

    def last_time(self) -> Any:
        """The primary source's last sample time, when it is a recorded file (else None)."""

        last = getattr(self.primary, "last_time", None)
        return last() if callable(last) else None

    def read_window(self, minutes: int, sample_seconds: int) -> pd.DataFrame:
        return self.primary.read_window(minutes, sample_seconds)

    def read_range(
        self,
        start: str | datetime,
        end: str | datetime,
        sample_seconds: int,
        *,
        tags: list[str] | None = None,
        include_boundary: bool = True,
    ) -> pd.DataFrame:
        foreign = self.registry.foreign_routes() if tags else {}
        groups: dict[str, list[str]] = defaultdict(list)
        for tag in tags or []:
            groups[foreign.get(tag, PRIMARY)].append(tag)
        if not foreign or set(groups) <= {PRIMARY}:
            self._failed = self._from_cache = None
            return self.primary.read_range(
                start, end, sample_seconds, tags=tags, include_boundary=include_boundary
            )
        frames: list[pd.DataFrame] = []
        failures: list[tuple[str, str]] = []
        cached = True
        for source_id, group in groups.items():
            try:
                source = (
                    self.primary if source_id == PRIMARY else self.registry.data(source_id).source
                )
                frame = source.read_range(
                    start, end, sample_seconds, tags=group, include_boundary=include_boundary
                )
            except Exception as exc:  # one unreachable source must not hide the others
                failures.extend((tag, str(exc) or type(exc).__name__) for tag in group)
                continue
            failures.extend(getattr(source, "failed_tags", []) or [])
            cached = cached and bool(getattr(source, "last_read_from_cache", False))
            if not frame.empty:
                frames.append(frame)
        self._failed, self._from_cache = failures, cached
        if not frames:
            details = "; ".join(f"{tag}: {reason}" for tag, reason in failures[:5])
            raise RuntimeError(t("No tag was loaded from the sources. {details}", details=details))
        frame = pd.concat(frames, axis=1).sort_index()
        frame = frame.loc[~frame.index.duplicated(keep="last")]
        return frame.loc[:, ~frame.columns.duplicated()]


def _endpoint(config: DataSourceConfig) -> str | None:
    from urllib.parse import urlsplit, urlunsplit

    if config.type == "csv":
        return Path(config.path or "").name or None
    value = config.endpoint_url if config.type == "opcua" else config.base_url
    if not value:
        return None
    parsed = urlsplit(value)
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{parsed.hostname or ''}{port}", parsed.path, "", ""))


def _settings(config: DataSourceConfig) -> dict[str, Any]:
    fields = set(EDITABLE.get(config.type, ())) | set(COMMON)
    settings = config.model_dump(mode="json", include=fields)
    if config.type == "pi_web_api":
        settings["tags"] = len(config.tags)
    return settings


def _close(source: Any) -> None:
    inner = getattr(source, "source", source)
    pool = getattr(inner, "_pool", None)
    if pool is not None:
        pool.shutdown(wait=False)
