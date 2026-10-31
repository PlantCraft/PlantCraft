"""The settings a source adapter reads, built from a Historian source row.

``SourceConfig`` carries the fields of PlantCraft's ``DataSourceConfig`` the adapters
use, so their code stays as it was ported; ``from_source`` maps a row of Historian's
catalogue (``{"id", "name", "kind", "endpoint", "namespace_uri", "username",
"options"}``) and the source's decrypted password onto it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from histcraft.config import data_folder
from histcraft.i18n import t

SOURCE_KINDS = ("pi_web_api", "opcua", "csv")


@dataclass
class SourceConfig:
    type: str = "csv"
    path: str | None = None
    server: str | None = None
    base_url: str = ""
    endpoint_url: str | None = None
    namespace_uri: str = ""
    # PI: kerberos, ntlm or basic. OPC UA: basic (user and password) or anonymous.
    auth_type: str = "kerberos"
    username: str | None = None
    # The decrypted password; never shown in repr.
    password: str | None = field(default=None, repr=False)
    verify_ssl: bool = True
    # Corporate CA file (PEM) for the PI Web API certificate; wins over verify_ssl.
    ca_bundle: str | None = None
    # PI Web API: "recorded" keeps the archived events; "interpolated" asks for a grid.
    read_mode: str = "recorded"
    # PI Web API: parallel tag reads, retries of transient failures (429, 5xx,
    # dropped connections) and the most values asked for in one call.
    max_workers: int = 4
    retries: int = 3
    page_size: int = 50000
    # Naive times (CSV files, the adapters' DataFrames) are local times in this zone.
    timezone: str = "UTC"
    timeout_seconds: float = 30.0
    # OPC UA: how far back the last value before a read's start is looked for.
    history_boundary_minutes: int = 1440
    # OPC UA secure channel (G2): mode, policy, trusted server thumbprint, the client's folder.
    security_mode: str = "None"
    security_policy: str = "Basic256Sha256"
    server_thumbprint: str = ""
    data_dir: str | None = None
    tags: list[str] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)

    def secret(self) -> str:
        """The password (stored encrypted in Historian's catalogue, given here in clear)."""

        return self.password or ""


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def from_source(source: dict[str, Any], password: str) -> SourceConfig:
    """The adapter settings of a Historian source row; ``ValueError`` for an unknown kind."""

    kind = str(source.get("kind") or "")
    if kind not in SOURCE_KINDS:
        raise ValueError(
            t(
                "Sources with history: {kinds} (not {kind}).",
                kinds=", ".join(SOURCE_KINDS),
                kind=kind or "?",
            )
        )
    options = dict(source.get("options") or {})
    endpoint = str(source.get("endpoint") or "").strip()
    username = str(source.get("username") or "").strip() or None
    common: dict[str, Any] = {
        "type": kind,
        "username": username,
        "password": password or None,
        "namespace_uri": str(source.get("namespace_uri") or ""),
        "timezone": str(options.get("timezone") or "UTC"),
    }
    if kind == "csv":
        return SourceConfig(**common, path=endpoint)
    timeout = _float(options.get("timeout_seconds"), 30.0)
    boundary = _int(options.get("history_boundary_minutes"), 1440, 0, 10**7)
    if kind == "opcua":
        return SourceConfig(
            **common,
            endpoint_url=endpoint,
            auth_type="basic" if username else "anonymous",
            timeout_seconds=timeout,
            history_boundary_minutes=boundary,
            security_mode=str(options.get("security_mode") or "None"),
            security_policy=str(options.get("security_policy") or "Basic256Sha256"),
            server_thumbprint=str(options.get("server_thumbprint") or ""),
            data_dir=data_folder(),
        )
    auth_type = str(options.get("auth_type") or "kerberos")
    if auth_type not in ("kerberos", "ntlm", "basic"):
        raise ValueError(t("PI authentication is kerberos, ntlm or basic."))
    read_mode = str(options.get("read_mode") or "recorded")
    return SourceConfig(
        **common,
        base_url=endpoint,
        server=str(options.get("server") or "").strip() or None,
        auth_type=auth_type,
        verify_ssl=bool(options.get("verify_ssl", True)),
        ca_bundle=str(options.get("ca_bundle") or "").strip() or None,
        read_mode=read_mode if read_mode in ("recorded", "interpolated") else "recorded",
        max_workers=_int(options.get("max_workers"), 4, 1, 32),
        retries=_int(options.get("retries"), 3, 0, 10),
        page_size=_int(options.get("page_size"), 50000, 100, 150000),
        timeout_seconds=timeout,
        history_boundary_minutes=boundary,
    )


# --- Shared by the adapters -------------------------------------------------------------

# Start of a per-tag error that only says the tag had nothing new (quiet in the logs).
NO_VALUE = "no value"


@dataclass(frozen=True)
class SignalInfo:
    tag: str
    name: str
    asset: str
    unit: str = ""
    description: str = ""
    data_type: str = "number"
    step: bool = False
    path: str = ""


def asset_from_tag(tag: str) -> str:
    """Group tags like ``FIC-101.PV`` or ``FIC101_PV`` under ``FIC-101``."""

    for separator in (".", ":", "/"):
        if separator in tag:
            return tag.rsplit(separator, 1)[0]
    return tag
