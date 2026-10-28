"""Settings (from the environment) and the loop and analysis contracts.

Every setting has a safe default and comes from an environment variable;
secrets (the app key) are never logged or stored by LinkCraft.

| Variable | Default | Meaning |
|---|---|---|
| ``PLANTCRAFT_URL`` | ``http://127.0.0.1:8060`` | PlantCraft API v1, as this server reaches it |
| ``PLANTCRAFT_PUBLIC_URL`` | empty (same origin) | PlantCraft as the browser reaches it (sign-in page) |
| ``PLANTCRAFT_APP_KEY`` | empty | App key for background work (rounds, schedules) |
| ``LINKCRAFT_DATA_DIR`` | ``var`` | Folder of the SQLite database |
| ``LINKCRAFT_ROOT_PATH`` | ``/link`` | Path prefix of the interface and API |
| ``LINKCRAFT_SCHEDULER_ENABLED`` | ``true`` | Run rounds and schedules in the background |
| ``LINKCRAFT_ROUND_MINUTES`` | ``10`` | Interval of the monitoring round |
| ``LINKCRAFT_WINDOW_MINUTES`` | ``1440`` | Data window each round analyses |
| ``LINKCRAFT_RESAMPLE_SECONDS`` | ``60`` | Regular grid the methods see |
| ``LINKCRAFT_TIMEZONE`` | ``UTC`` | Time zone of schedules (daily at 08:00...) |
| ``LINKCRAFT_LOOP_ASSET_KIND`` | ``loop`` | PlantCraft asset type id read as control loops |
| ``LINKCRAFT_SIGNAL_ROUND_MINUTES`` | ``15`` | First interval of the Signal quality algorithm |
| ``LINKCRAFT_SIGNAL_WINDOW_HOURS`` | ``24`` | First data window of the Signal quality algorithm |
| ``LINKCRAFT_PROCESSES`` | CPUs - 1 | Worker processes for the methods (``0``: in thread) |
| ``LINKCRAFT_ENGINE`` | ``process`` | Where the schedules and the queue run: ``process`` (a process of its own, started by the server), ``external`` (a separate service runs ``linkcraft engine``), ``inline`` (in the server's process) |
| ``LINKCRAFT_WORKERS`` | CPUs (2 to 8) | Executions the engine runs at the same time |
| ``LINKCRAFT_TASK_TIMEOUT_SECONDS`` | ``300`` | Longest one loop's analysis may take |
| ``LINKCRAFT_TASK_MEMORY_MB`` | ``4096`` | Memory each analysis process may take beyond its start (``0``: no limit) |
| ``LINKCRAFT_APP_TOML`` | ``app.toml`` of the checkout | The manifest ``/api/meta`` serves (image: ``/app``) |
| ``LINKCRAFT_REVISION`` | ``git`` of the checkout | Source revision ``/api/meta`` reports (image: build arg) |
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from plantcraft_sdk.server.settings import AppSettings, env_flag, env_number, env_text
from pydantic import BaseModel, Field, field_validator

from linkcraft import APP_ID
from linkcraft.i18n import t


def positive(name: str, default: float) -> float:
    """A number from the environment above zero; ``default`` otherwise."""

    return env_number(name, default, allow_zero=False)


class LoopSignals(BaseModel):
    """PlantCraft signal ids (API v1) of each role of a loop.

    ``pv`` is ``None`` only on an incomplete record read from a PlantCraft asset (see
    ``AssetRecord.missing_roles``); such a loop is listed but never analysed.
    """

    pv: str | None = None
    sp: str | None = None
    op: str | None = None
    mode: str | None = None
    secondary: str | None = None

    @field_validator("pv")
    @classmethod
    def validate_pv(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError(t("The PV signal is required."))
        return value


class AssetRecord(BaseModel):
    """What PlantCraft's asset record says about a loop, as of the last sync.

    Owned by PlantCraft (refreshed by every sync, never edited here). ``loop_type`` and
    ``criticality`` are kept as PlantCraft gave them, even when LinkCraft does not know the
    value; ``missing_roles`` lists the required signal roles the asset has no signal for.
    """

    type_id: str = "loop"
    type_path: list[str] = Field(default_factory=list)
    loop_type: str | None = None
    criticality: str | None = None
    action: str | None = None
    controller: str | None = None
    relations: list[dict[str, str]] = Field(default_factory=list)
    required_roles: list[str] = Field(default_factory=list)
    missing_roles: list[str] = Field(default_factory=list)
    # Where the required roles came from: "asset_types" (GET /api/v1/asset-types) or "fallback".
    roles_source: str = "fallback"


class LoopConfig(BaseModel):
    """One control loop as LinkCraft analyses it."""

    loop_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    area: str = "No area"
    service: str = ""
    unit: str = ""
    enabled: bool = True
    signals: LoopSignals
    profile_id: str = "all"
    enabled_methods: list[str] | None = None
    method_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    health_excluded_methods: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Loops from PlantCraft: the asset record (None on rows synced before the asset catalog).
    asset_record: AssetRecord | None = None
    # Settings a person chose in LinkCraft ("profile_id", "criticality"); they win over the
    # defaults derived from the asset record.
    set_here: list[str] = Field(default_factory=list)

    @property
    def incomplete(self) -> bool:
        """An asset without a signal for a required role: listed, never analysed."""

        return bool(self.asset_record and self.asset_record.missing_roles) or not self.signals.pv

    @field_validator("loop_id", "name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("The field is required."))
        return value


ROLES = ("pv", "sp", "op", "mode", "secondary")


class AnalysisConfig(BaseModel):
    """How a round analyses each loop (window, grid and which methods mean what)."""

    interval_minutes: float = Field(default=10.0, gt=0)
    window_minutes: int = Field(default=1440, gt=0)
    resample_seconds: int = Field(default=60, gt=0)
    enabled_methods: list[str] = Field(
        default_factory=lambda: [
            "error_metrics_basic",
            "pv_variability",
            "op_saturation_fraction",
            "op_travel_reversal",
            "setpoint_activity",
            "sensor_noise_ratio",
            "oscillation_autocorrelation",
            "stiction_screening",
            "manual_mode_fraction",
        ]
    )
    method_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Run the data quality gate before the CPM methods.
    data_quality_gate: bool = True
    health_excluded_methods: list[str] = Field(default_factory=lambda: ["stiction_screening"])
    # Operator behaviour, not controller performance: shown beside the score as
    # context, never multiplied into it (a busy operator must not zero a loop).
    context_methods: list[str] = Field(
        default_factory=lambda: ["operational_interventions", "manual_mode_fraction"]
    )
    # Fault screenings outside the score; a warning or bad result is flagged as a
    # diagnostic to confirm in the field (a good score can hide a sticky valve).
    diagnostic_methods: list[str] = Field(
        default_factory=lambda: [
            "stiction_screening",
            "oscillation_autocorrelation",
            "sensor_noise_ratio",
        ]
    )

    @classmethod
    def from_environment(cls) -> AnalysisConfig:
        return cls(
            interval_minutes=positive("LINKCRAFT_ROUND_MINUTES", 10.0),
            window_minutes=int(positive("LINKCRAFT_WINDOW_MINUTES", 1440)),
            resample_seconds=int(positive("LINKCRAFT_RESAMPLE_SECONDS", 60)),
        )


@dataclass
class Settings(AppSettings):
    APP_ID = APP_ID

    root_path: str = "/link"
    scheduler_enabled: bool = True
    timezone: str = "UTC"
    loop_asset_kind: str = "loop"
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    # The Signal quality algorithm's first interval and window (then edited in the app).
    signal_interval_minutes: float = 15.0
    signal_window_hours: float = 24.0
    # Process models (FMUs): worker processes that run them, the time one run may take, the
    # largest file an admin may publish, and whether publishing is on.
    simulation_workers: int = 2
    simulation_timeout: float = 60.0
    max_model_mb: float = 200.0
    model_upload: bool = True
    # Where the engine runs (``engine.process``) and how many executions it runs at once
    # (0: ``engine.dispatcher.default_slots``).
    engine: str = "inline"
    workers: int = 0

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def blocks_dir(self) -> Path:
        """Every saved version of the site's blocks, one file each (``blocks.site``)."""

        return self.data_dir / "blocks"

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            **cls.common(APP_ID, "/link"),
            scheduler_enabled=env_flag("LINKCRAFT_SCHEDULER_ENABLED", True),
            timezone=env_text("LINKCRAFT_TIMEZONE", "UTC"),
            loop_asset_kind=env_text("LINKCRAFT_LOOP_ASSET_KIND", "loop"),
            analysis=AnalysisConfig.from_environment(),
            signal_interval_minutes=positive("LINKCRAFT_SIGNAL_ROUND_MINUTES", 15.0),
            signal_window_hours=min(31 * 24.0, positive("LINKCRAFT_SIGNAL_WINDOW_HOURS", 24.0)),
            simulation_workers=max(1, int(positive("LINKCRAFT_SIMULATION_WORKERS", 2))),
            simulation_timeout=max(5.0, positive("LINKCRAFT_SIMULATION_TIMEOUT", 60.0)),
            max_model_mb=max(1.0, positive("LINKCRAFT_MAX_MODEL_MB", 200.0)),
            model_upload=env_flag("LINKCRAFT_MODEL_UPLOAD", True),
            engine=engine_mode(env_text("LINKCRAFT_ENGINE", "process")),
            workers=int(env_number("LINKCRAFT_WORKERS", 0)),
        )


ENGINE_MODES = ("process", "external", "inline")


def engine_mode(value: str) -> str:
    value = value.strip().lower()
    if value not in ENGINE_MODES:
        raise ValueError(
            f"LINKCRAFT_ENGINE must be one of {', '.join(ENGINE_MODES)}, not {value!r}"
        )
    return value


# The manifest (app.toml) -----------------------------------------------------

CHECKOUT = Path(__file__).resolve().parents[2]


def manifest_path() -> Path | None:
    """``LINKCRAFT_APP_TOML``, else ``app.toml`` of a source checkout, else the image's copy."""

    named = os.environ.get("LINKCRAFT_APP_TOML", "").strip()
    candidates = [Path(named)] if named else []
    candidates += [CHECKOUT / "app.toml", Path("/app/app.toml")]
    return next((path for path in candidates if path.is_file()), None)


@cache
def app_manifest() -> dict[str, Any]:
    """LinkCraft's ``app.toml`` (the PlantCraft app standard, section 4), read once."""

    path = manifest_path()
    if path is None:
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


@cache
def revision() -> str:
    """The source revision: ``LINKCRAFT_REVISION`` (set by the image build), else git, else unknown."""

    named = os.environ.get("LINKCRAFT_REVISION", "").strip()
    if named:
        return named
    if (CHECKOUT / ".git").exists():
        try:
            answer = subprocess.run(
                ["git", "-C", str(CHECKOUT), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        return answer.stdout.strip() or "unknown"
    return "unknown"
