"""The catalog's shapes and rules without the database: what a source and a point may hold
(``SourceIn``, ``PointIn``, ``PointPatch``), the kinds, modes and settings they take, and
``CatalogError``. ``histcraft.catalog.store`` keeps them in its tables; the routers validate
with these (PlantCraft ``docs/app-standard.md``, section 5)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from histcraft.catalog.gateway import OPTIONS as GATEWAY_OPTIONS
from histcraft.catalog.gateway import check as check_gateway
from histcraft.config import csv_pattern_allowed, outside_csv_folders
from histcraft.i18n import t
from histcraft.kinds import KINDS, RUNS

SOURCE_KINDS = (
    "pi_web_api",
    "opcua",
    "csv",
    "mqtt",
    "modbus",
    "sql",
    "derived",
    "system",
    "calc",
    "import",
)
# Sources read by the gateway (Telegraf, ``collector.gateway``): it pushes their values to the
# collector, which archives them like any read value. They have no history to read back.
GATEWAY_KINDS = ("mqtt", "modbus", "sql")
# Kinds an administrator adds on the Sources page; derived sources appear on an app's first write,
# the system source on PlantCraft's.
PLANT_KINDS = ("pi_web_api", "opcua", "csv")
# A CSV file loaded once (Import & export): one source per import, never read again.
IMPORT_KIND = "import"
IMPORT_PREFIX = "import-"
# Kinds written through the API (an app's series, the suite's health), never read from a plant.
WRITTEN_KINDS = ("derived", "system")
# The suite's own health: one source, written by PlantCraft only, kept 90 days.
SYSTEM_SOURCE = "system"
SYSTEM_RETENTION_DAYS = 90
# Calculated points (``catalog.expressions``): one source, created with its first point; the
# collector evaluates each point's formula (its address) on its scan and archives the result.
CALC_SOURCE = "calc"
# Apps merged into another (owner, 2026-10-22): their derived sources stay readable, marked with
# the app that took over, and an admin may remove them. Twin's are removed on start (owner,
# 2026-10-23): Link writes its own series since 0.3.0.
RETIRED_APPS = {"twincraft": "linkcraft", "cpmcraft": "linkcraft", "datacraft": "linkcraft"}
DROPPED_APPS = ("twincraft",)
# Sources whose values come with a quality (OPC UA status, PI's questionable and substituted).
# A calculated point's quality is the worst of its inputs'.
QUALITY_KINDS = ("opcua", "pi_web_api", "calc")
MODES = ("source", "archive", "both")
DEFAULT_MODES = {
    "pi_web_api": "source",
    "opcua": "archive",
    "csv": "archive",
    "import": "archive",
    "derived": "archive",
    "system": "archive",
    "calc": "archive",
    "mqtt": "archive",
    "modbus": "archive",
    "sql": "archive",
}
# Kinds the collector reads live (archive and both modes); CSV files are checked for new rows.
LIVE_KINDS = ("opcua", "calc", "csv", *GATEWAY_KINDS)
# Kinds that exist only in the archive: no history to read back (mode archive only).
ARCHIVE_ONLY_KINDS = ("calc", "csv", IMPORT_KIND, *GATEWAY_KINDS)
# Kinds whose history can be read back from the source.
HISTORY_KINDS = ("pi_web_api", "opcua")
# ``runs``: one series per execution of an app (H2), written by ``/derived/runs`` only.
POINT_KINDS = (*KINDS, RUNS)
# Modes that need the collector, and why other kinds refuse them (docs/gaps.md G15).
COLLECTED = ("archive", "both")
NOT_COLLECTED = "PI Web API points are read from the source (mode source)."
ONLY_ARCHIVED = (
    "Calculated, CSV, imported, MQTT, Modbus and SQL points exist only in the archive"
    " (mode archive)."
)
DEFAULT_SETTINGS: dict[str, Any] = {
    # Archived values older than this are deleted (per point, unless it sets its own).
    "retention_days": 400,
    # New points: scan period, compression deviation as % of span (of the value when no range
    # is known), max interval. A steady signal is still archived every 10 min: the apps' data
    # checks (Link's availability: an interval above 10 min is a gap) see a constant setpoint as
    # data, not as hours of gaps that make every loop "data not usable".
    # Compression like PI's (round 8 D1, 2026-10-25): an exception of 0.1 % and a compression
    # deviation of 0.2 % of the span (of the value when no range is known).
    "default_scan_seconds": 1.0,
    "default_deviation_percent": 0.2,
    "default_max_seconds": 600.0,
    "default_exception_percent": 0.1,
}
# A source may override these general settings for its points (None: the general value).
SOURCE_SETTINGS = (
    "retention_days",
    "default_scan_seconds",
    "default_deviation_percent",
    "default_max_seconds",
)
# Named compression profiles (D1): (exception %, deviation %) of the span. The standard one
# ("") is the general settings (or the source's); a point's own deviation is "custom".
PROFILES: dict[str, tuple[float, float]] = {"fine": (0.05, 0.1), "none": (0.0, 0.0)}
PROFILE_NAMES = ("", *PROFILES)
# Settings that may be 0 (0 % keeps every change); the others must be positive.
ZERO_SETTINGS = ("default_deviation_percent", "default_exception_percent")
# A point's own setting -> the source and general setting it falls back to.
POINT_SETTINGS = {
    "retention_days": "retention_days",
    "scan_seconds": "default_scan_seconds",
    "deviation": "default_deviation_percent",
    "max_seconds": "default_max_seconds",
}
# The settings a point's ``managed_by`` (the app that writes it) sets; people get a 409.
MANAGED = (
    "retention_days",
    "scan_seconds",
    "deviation",
    "max_seconds",
    "step",
    "profile",
    "exception",
)
# Point settings whose column is NOT NULL: inheritance is recorded in ``inherits``.
INHERITABLE = ("scan_seconds", "deviation", "max_seconds")
_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
# OPC UA secure channel choices (``collector.certificates`` holds what they mean).
SECURITY_MODES = ("None", "Sign", "SignAndEncrypt")
SECURITY_POLICIES = ("Basic256Sha256", "Aes128_Sha256_RsaOaep", "Aes256_Sha256_RsaPss")
_THUMBPRINT = re.compile(r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
# Options a source of each kind takes beyond endpoint, user and password (docs/data-layer.md).
SOURCE_OPTIONS: dict[str, dict[str, Any]] = {
    "pi_web_api": {
        "server": "",
        "auth_type": "kerberos",
        "verify_ssl": True,
        "ca_bundle": "",
        "read_mode": "recorded",
        "max_workers": 4,
        "retries": 3,
        "page_size": 50000,
        "timeout_seconds": 30.0,
        "timezone": "UTC",
        "history_boundary_minutes": 1440,
    },
    "opcua": {
        "timeout_seconds": 30.0,
        "timezone": "UTC",
        "history_boundary_minutes": 1440,
        # Secure channel (G2): mode, policy and the SHA-256 of the server certificate trusted.
        "security_mode": "None",
        "security_policy": "Basic256Sha256",
        "server_thumbprint": "",
    },
    # A file or a pattern in one folder (/csv/lims/*.csv), checked every check_minutes.
    "csv": {"timezone": "UTC", "check_minutes": 5.0},
    # What was imported, kept for the list (Import & export); set by the server only.
    IMPORT_KIND: {
        "file_name": "",
        "bytes": 0,
        "sha256": "",
        "shape": "",
        "timezone": "UTC",
        "rows": 0,
        "values": 0,
        "start_ms": None,
        "end_ms": None,
        "imported_by": "",
        "warnings": 0,
        # How the file is read (sources.csv_table.ReadOptions), used again for the next file.
        "read": {},
        # The folder the import repeats from (owner, 2026-10-26): {"pattern", "check_minutes",
        # "by"}; empty when only a person adds its files. Set by the server only.
        "repeat": {},
        # Each file imported into it, newest first: at, by, file_name, rows, values, start_ms,
        # end_ms (at most RUNS_KEPT).
        "runs": [],
    },
    "derived": {},
    "system": {},
    "calc": {},
    **GATEWAY_OPTIONS,
}


def derived_source(app: str) -> str:
    """The source id of an app's derived signals: ``app-<app id>`` (a plant source may share
    the app's own id, as the Simulator does)."""

    return f"app-{app}"


def split_signal(signal_id: str) -> tuple[str, str]:
    """``<source id>:<tag>`` as ``(source id, tag)``; ``("", signal_id)`` when it has no source."""

    source, sep, tag = signal_id.partition(":")
    if sep and tag and _SOURCE_ID.match(source):
        return source, tag
    return "", signal_id


# Days a retired point keeps its archive before the collector deletes it for good.
RETIRED_DAYS = 30
_COLUMN = re.compile(r"^[a-z_]+$")


class SourceIn(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    kind: str = "opcua"
    # OPC UA: opc.tcp:// URL; PI Web API: its https:// base URL; CSV: the file's path.
    endpoint: str = Field(default="", max_length=500)
    namespace_uri: str = Field(default="", max_length=500)
    username: str = Field(default="", max_length=200)
    # The password: from the environment variable named here (``HISTCRAFT_SECRET_<NAME>``),
    # or typed (``password``, stored encrypted, never sent back). ``None`` keeps the stored one.
    password_env: str = Field(default="", max_length=100)
    password: str | None = Field(default=None, max_length=500, exclude=True, repr=False)
    mode: str = ""
    options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    # Overrides of the general settings for this source's points (None: the general value).
    # On an update, a field left out keeps the stored override; null clears it.
    # 0 keeps the values forever.
    retention_days: int | None = Field(default=None, ge=0, le=36500)
    default_scan_seconds: float | None = Field(default=None, ge=0.1, le=86400)
    default_deviation_percent: float | None = Field(default=None, ge=0, le=100)
    default_max_seconds: float | None = Field(default=None, ge=1, le=7 * 86400)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SOURCE_ID.match(value):
            raise ValueError(t("Use lowercase letters, digits, - and _ (up to 40)."))
        return value

    @field_validator("kind")
    @classmethod
    def valid_kind(cls, value: str) -> str:
        if value not in SOURCE_KINDS:
            raise ValueError(t("Supported sources: {kinds}.", kinds=", ".join(SOURCE_KINDS)))
        return value

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value: str) -> str:
        if value and value not in MODES:
            raise ValueError(t("mode is source, archive or both."))
        return value

    @model_validator(mode="after")
    def valid_endpoint(self) -> SourceIn:
        self.endpoint = self.endpoint.strip()
        known = SOURCE_OPTIONS[self.kind]
        unknown = set(self.options) - set(known)
        if unknown:
            raise ValueError(t("Unknown option: {name}.", name=sorted(unknown)[0]))
        self.options = {key: self.options.get(key, default) for key, default in known.items()}
        if (self.id == SYSTEM_SOURCE) != (self.kind == "system"):
            raise ValueError(t("The source system is reserved for the suite's health."))
        if (self.id == CALC_SOURCE) != (self.kind == "calc"):
            raise ValueError(t("The source calc is reserved for calculated signals."))
        if self.kind in WRITTEN_KINDS or self.kind in ("calc", IMPORT_KIND):
            self.endpoint = self.namespace_uri = self.username = self.password_env = ""
            self.password = None
            self.mode = "archive"
        elif self.kind == "opcua" and not self.endpoint.startswith("opc.tcp://"):
            raise ValueError(t("An OPC UA endpoint starts with opc.tcp://"))
        elif self.kind == "opcua":
            if self.options["security_mode"] not in SECURITY_MODES:
                raise ValueError(t("security_mode is None, Sign or SignAndEncrypt."))
            if self.options["security_policy"] not in SECURITY_POLICIES:
                raise ValueError(
                    t("security_policy is one of {names}.", names=", ".join(SECURITY_POLICIES))
                )
            pinned = str(self.options["server_thumbprint"] or "").strip().upper()
            if pinned and not _THUMBPRINT.match(pinned):
                raise ValueError(t("server_thumbprint is a SHA-256 in AB:CD:... form."))
            self.options["server_thumbprint"] = pinned
        elif self.kind == "pi_web_api":
            if not self.endpoint.startswith("https://"):
                raise ValueError(t("A PI Web API address starts with https://"))
            if not str(self.options["server"]).strip():
                raise ValueError(t("Name the PI Data Archive server."))
            if self.options["auth_type"] not in ("kerberos", "ntlm", "basic"):
                raise ValueError(t("PI Web API authentication is kerberos, ntlm or basic."))
            if self.options["read_mode"] not in ("recorded", "interpolated"):
                raise ValueError(t("read_mode is recorded or interpolated."))
        elif self.kind in GATEWAY_KINDS:
            self.options = check_gateway(self.kind, self.endpoint, self.options)
            self.namespace_uri = ""
            self.mode = "archive"
        elif self.kind == "csv" and not self.endpoint:
            raise ValueError(
                t("Give the path of the CSV file, or a pattern such as /csv/lims/*.csv.")
            )
        elif self.kind == "csv" and not csv_pattern_allowed(self.endpoint):
            raise ValueError(outside_csv_folders())
        elif self.kind == "csv":
            try:
                minutes = float(self.options["check_minutes"])
            except (TypeError, ValueError):
                minutes = 0.0
            if not 0.5 <= minutes <= 1440:
                raise ValueError(t("Check the files every 0.5 to 1440 minutes."))
            self.options["check_minutes"] = minutes
            self.mode = "archive"
        if self.kind in HISTORY_KINDS and self.kind not in LIVE_KINDS and self.mode in COLLECTED:
            raise ValueError(NOT_COLLECTED)
        return self

    @field_validator("password_env")
    @classmethod
    def valid_env(cls, value: str) -> str:
        value = value.strip()
        if value and not re.match(r"^HISTCRAFT_SECRET_[A-Z0-9_]{1,60}$", value):
            raise ValueError(t("The password variable must be named HISTCRAFT_SECRET_<NAME>."))
        return value


class PointIn(BaseModel):
    tag: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=40)
    # Where the source finds it (OPC UA node id, PI tag, CSV column); the tag when empty.
    address: str = Field(default="", max_length=500)
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=500)
    unit: str = Field(default="", max_length=40)
    kind: str = "number"
    step: bool = False
    low: float | None = None
    high: float | None = None
    scan_seconds: float | None = Field(default=None, ge=0.1, le=86400)
    deviation: float | None = Field(default=None, ge=0)
    # The exception in engineering units (None: the profile's) and the compression profile.
    exception: float | None = Field(default=None, ge=0)
    profile: str | None = None
    max_seconds: float | None = Field(default=None, ge=1, le=7 * 86400)
    # 0 keeps the values forever.
    retention_days: int | None = Field(default=None, ge=0, le=36500)
    mode: str = ""
    enabled: bool = True

    @field_validator("tag")
    @classmethod
    def stripped(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ch in value for ch in "\x00\n\r\t"):
            raise ValueError(t("The field is required and must be one line."))
        return value

    @field_validator("address")
    @classmethod
    def one_line(cls, value: str) -> str:
        value = value.strip()
        if any(ch in value for ch in "\x00\n\r\t"):
            raise ValueError(t("The field is required and must be one line."))
        return value

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value: str) -> str:
        if value and value not in MODES:
            raise ValueError(t("mode is source, archive or both."))
        return value

    @field_validator("kind")
    @classmethod
    def valid_kind(cls, value: str) -> str:
        # A runs point is an app's (``/derived/runs``), never added as a plant point.
        if value not in KINDS:
            raise ValueError(t("kind is one of {kinds}.", kinds=", ".join(KINDS)))
        return value

    @field_validator("profile")
    @classmethod
    def valid_profile(cls, value: str | None) -> str | None:
        return _valid_profile(value)


def _valid_profile(value: str | None) -> str | None:
    if value is not None and value not in PROFILE_NAMES:
        raise ValueError(t("profile is empty (standard), fine or none."))
    return value


class PointPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=40)
    step: bool | None = None
    low: float | None = None
    high: float | None = None
    # null: take the value from the source, else the general settings.
    scan_seconds: float | None = Field(default=None, ge=0.1, le=86400)
    deviation: float | None = Field(default=None, ge=0)
    # The exception in engineering units (None: the profile's) and the compression profile.
    exception: float | None = Field(default=None, ge=0)
    profile: str | None = None
    max_seconds: float | None = Field(default=None, ge=1, le=7 * 86400)
    # 0 keeps the values forever.
    retention_days: int | None = Field(default=None, ge=0, le=36500)
    # Empty: the source's mode.
    mode: str | None = None
    enabled: bool | None = None
    # A calculated point's formula (any other point's address never changes).
    address: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value: str | None) -> str | None:
        if value and value not in MODES:
            raise ValueError(t("mode is source, archive or both."))
        return value

    @field_validator("profile")
    @classmethod
    def valid_profile(cls, value: str | None) -> str | None:
        return _valid_profile(value)


class CatalogError(ValueError):
    """A change the catalog refuses; the message is for people (409 or 404)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def secret_follows(saved: dict[str, Any], data: SourceIn) -> None:
    """A stored password only goes to the server and user it was typed for: a source whose
    address or user changed asks for it again (422), so it never reaches another server."""

    def target(endpoint: Any, username: Any) -> tuple[str, str]:
        return str(endpoint or "").strip().rstrip("/"), str(username or "").strip()

    if target(saved.get("endpoint"), saved.get("username")) != target(data.endpoint, data.username):
        raise CatalogError(
            t(
                "The server changed: type the password again, so the saved one is never sent "
                "to another server."
            ),
            422,
        )
