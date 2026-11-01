"""Scenario contracts of PlantCraft: the source, how it is read, storage and loops."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from plantcraft.i18n import t
from plantcraft_sdk.server.settings import env_flag  # noqa: F401 (one rule for the suite)

_ZONE_SECONDS = 30.0
_zone_reader: Any = None
_zone_cache: tuple[float, str | None] = (0.0, None)


def valid_zone(name: str) -> bool:
    """Whether ``name`` is an IANA time zone this server knows (``Etc/GMT+3`` is UTC−3)."""

    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def use_installation_zone(reader: Any) -> None:
    """Where the zone an administrator saved in Settings › Installation is read (``None``: nowhere).

    The installation store registers itself; every worker reads the database at most every
    30 seconds, so a change reaches all of them within that."""

    global _zone_reader, _zone_cache
    _zone_reader = reader
    _zone_cache = (0.0, None)


def _saved_zone(fresh: bool) -> str | None:
    import time

    global _zone_cache
    if _zone_reader is None:
        return None
    now = time.monotonic()
    if not fresh and now - _zone_cache[0] < _ZONE_SECONDS:
        return _zone_cache[1]
    try:
        zone = _zone_reader()
    except Exception:  # a database being replaced (restore) never breaks a clock
        zone = None
    _zone_cache = (now, zone)
    return zone


def plant_timezone(*, fresh: bool = False) -> Any:
    """The installation's time zone: the one saved in Settings › Installation, else
    ``PLANTCRAFT_TIMEZONE`` (an IANA name such as ``America/Sao_Paulo``, written by
    ``install.sh``), else UTC. It says where a day, a shift or "today" begins and is the
    "Local time" screens show. Stored times are always UTC (``plantcraft.db.utc_text``)."""

    from zoneinfo import ZoneInfo

    for name in (_saved_zone(fresh), (os.environ.get("PLANTCRAFT_TIMEZONE") or "").strip()):
        if name and valid_zone(name):
            return ZoneInfo(name)
    return ZoneInfo("UTC")


def resolve_zone(name: str | None) -> Any:
    """The zone a saved setting means: ``local`` (or nothing, or an unknown name) is the
    installation's (a schedule follows the installation when it changes)."""

    from zoneinfo import ZoneInfo

    value = (name or "").strip()
    if value and value != "local" and valid_zone(value):
        return ZoneInfo(value)
    return plant_timezone()


def plant_clock(moment: Any, form: str = "%d %b %Y %H:%M") -> str:
    """An instant (aware, or naive meaning UTC) as text on the plant's wall clock: what a message,
    a notification or a document shows a person (stored times stay UTC; owner, 2026-10-27:
    "Deixe tudo no time zone do usuário")."""

    from datetime import timezone

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(plant_timezone()).strftime(form)


def plant_today() -> str:
    """Today's date where the plant is (``YYYY-MM-DD``)."""

    from datetime import datetime

    return datetime.now(plant_timezone()).date().isoformat()


class DataSourceConfig(BaseModel):
    type: Literal["csv", "pi_web_api", "opcua"] = "csv"
    path: str | None = None
    server: str | None = None
    # No default address: the administrator names the plant's own PI Web API.
    base_url: str = ""
    endpoint_url: str | None = None
    namespace_uri: str = "urn:processcraft:plantcraft"
    auth_type: Literal["kerberos", "ntlm", "basic", "anonymous"] = "kerberos"
    username: str | None = None
    password_env: str | None = None
    # A password typed in the interface for a source added at runtime (kept
    # encrypted in the database); never dumped. Scenario files use password_env.
    password: str | None = Field(default=None, exclude=True, repr=False)
    verify_ssl: bool = True
    # Corporate CA file (PEM) for the PI Web API certificate; wins over verify_ssl.
    ca_bundle: str | None = None
    # PI Web API: "recorded" keeps the archived events (as the OPC UA source
    # does); "interpolated" asks the server for a regular grid.
    read_mode: Literal["recorded", "interpolated"] = "recorded"
    # PI Web API: parallel tag reads, retries of transient failures (429, 5xx,
    # dropped connections) and the most values asked for in one call.
    max_workers: int = Field(default=4, ge=1, le=32)
    retries: int = Field(default=3, ge=0, le=10)
    page_size: int = Field(default=50000, ge=100, le=150000)
    timezone: str = "America/Sao_Paulo"
    timeout_seconds: float = Field(default=30.0, gt=0)
    history_boundary_minutes: int = Field(default=1440, ge=0)
    # Hours of history kept in the local cache (0 turns the cache off).
    history_cache_hours: int = Field(default=72, ge=0)
    tags: list[str] = Field(default_factory=list)
    mapping: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source(self, info: ValidationInfo) -> "DataSourceConfig":
        # A source added at runtime is browsed first; its tags come with use.
        needs_tags = not (info.context or {}).get("added_source")
        if self.type == "csv" and not self.path:
            raise ValueError(t("The CSV source needs the 'path' field."))
        if self.type == "pi_web_api":
            if not self.base_url:
                raise ValueError(t("The PI Web API source needs the 'base_url' field."))
            if not self.server:
                raise ValueError(t("The PI Web API source needs the 'server' field."))
            if needs_tags and not self.tags:
                raise ValueError(t("The PI Web API source needs at least one tag."))
            if self.auth_type == "anonymous":
                raise ValueError(t("The PI source does not accept anonymous authentication."))
        if self.type == "opcua":
            if not self.endpoint_url:
                raise ValueError(t("The OPC UA source needs the 'endpoint_url' field."))
            if needs_tags and not self.tags:
                raise ValueError(t("The OPC UA source needs at least one tag."))
        return self

    def secret(self) -> str:
        """The password: typed in the interface, else read from ``password_env``."""

        return self.password or os.environ.get(self.password_env or "", "")


class LoopSignals(BaseModel):
    pv: str
    sp: str | None = None
    op: str | None = None
    mode: str | None = None
    secondary: str | None = None

    @field_validator("pv")
    @classmethod
    def validate_pv(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("The PV variable is required."))
        return value


class LoopConfig(BaseModel):
    """A control loop the scenario describes: placed in the asset tree as a ``loop`` asset.

    Analysis settings (protocols, methods, parameters) belong to the app that analyses
    loops; scenario files may still carry them and they are ignored here.
    """

    loop_id: str
    name: str
    area: str = "No area"
    service: str = ""
    unit: str = ""
    signals: LoopSignals
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("loop_id", "name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("The field is required."))
        return value


class AnalysisConfig(BaseModel):
    """How the data is read: the expected cadence and the grid of history reads."""

    # Minutes between new samples one should expect; three without data mark the source stale.
    interval_minutes: float = Field(default=10.0, gt=0)
    resample_seconds: int = Field(default=60, gt=0)


class StorageConfig(BaseModel):
    sqlite_path: str = "var/processcraft.sqlite3"


class DashboardScenario(BaseModel):
    name: str
    display_name: str
    description: str = ""
    source: DataSourceConfig
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    loops: list[LoopConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_loop_ids(self) -> "DashboardScenario":
        loop_ids = [loop.loop_id for loop in self.loops]
        if len(loop_ids) != len(set(loop_ids)):
            raise ValueError(t("Loop ids must be unique."))
        return self


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _read_scenario_dict(path: Path, visited: set[Path] | None = None) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    visited = set() if visited is None else visited
    if resolved in visited:
        raise ValueError(f"Circular scenario inheritance: {resolved}")
    visited.add(resolved)

    with resolved.open(encoding="utf-8") as file:
        payload = json.load(file)

    base_ref = payload.pop("extends", None)
    if not base_ref:
        return payload

    base_path = Path(base_ref)
    if not base_path.is_absolute():
        base_path = resolved.parent / base_path
    if not base_path.is_file():
        raise FileNotFoundError(f"Base scenario not found: {base_path}")
    return _deep_merge(_read_scenario_dict(base_path, visited), payload)


def _expand_path(value: str, project_root: Path) -> str:
    expanded = os.path.expandvars(os.path.expanduser(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = project_root / path
    return str(path.resolve())


def load_scenario(
    scenario_path: str | Path,
    *,
    project_root: str | Path | None = None,
    data_override: str | Path | None = None,
) -> DashboardScenario:
    """Load and resolve one monitoring scenario."""
    path = Path(scenario_path).expanduser().resolve()
    root = (
        Path(project_root).expanduser().resolve() if project_root else path.parent.parent.resolve()
    )
    payload = _read_scenario_dict(path)

    source = payload.setdefault("source", {})
    if data_override is not None:
        source["type"] = "csv"
        source["path"] = str(Path(data_override).expanduser().resolve())
    elif source.get("path"):
        source["path"] = _expand_path(source["path"], root)
    if source.get("type") == "opcua":
        endpoint_override = os.environ.get("PLANTCRAFT_OPCUA_ENDPOINT")
        if endpoint_override:
            source["endpoint_url"] = endpoint_override
        if not source.get("tags"):
            source["tags"] = list(
                dict.fromkeys(
                    signal
                    for loop in payload.get("loops", [])
                    for signal in (loop.get("signals") or {}).values()
                    if signal
                )
            )

    storage = payload.setdefault("storage", {})
    storage["sqlite_path"] = _expand_path(
        storage.get("sqlite_path", "var/processcraft.sqlite3"),
        root,
    )
    return DashboardScenario.model_validate(payload)
