"""Canonical v1 benchmark manifests, digests, and compatibility checks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Final

from .catalog import (
    Catalog,
    LoopDefinition,
    ScenarioDefinition,
    SignalDefinition,
    load_catalog,
)
from .model import (
    SCENARIO_PARAMETERS,
    build_coupling_graph,
    model_definition_for,
    validate_model,
)
from .profiles import (
    RuntimeProfileError,
    load_runtime_profiles,
    validate_runtime_profile,
)

BENCHMARK_VERSION: Final = "0.4.0"
NAMESPACE_URI: Final = "urn:processcraft:plantcraft"
BENCHMARK_MANIFEST_SCHEMA: Final = "process-plant-opcua/benchmark-manifest/v1"
DATASET_MANIFEST_SCHEMA: Final = "process-plant-opcua/dataset-manifest/v1"
OBSERVATION_SCHEMA: Final = "process-plant-opcua/observation/v1"
TRUTH_FRAME_SCHEMA: Final = "process-plant-opcua/truth-frame/v1"
DIGEST_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
VERSION_PATTERN: Final = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")

_MANIFEST_KEYS: Final = {
    "benchmark_version",
    "catalog_digest",
    "couplings",
    "loops",
    "loop_models",
    "namespace_uri",
    "runtime_profiles",
    "scenarios",
    "scenario_parameterizations",
    "schema",
    "signals",
}
_DATASET_MANIFEST_KEYS: Final = {
    "benchmark_manifest_digest",
    "benchmark_version",
    "catalog_digest",
    "duration_seconds",
    "end_at",
    "frames",
    "integration_step_seconds",
    "observation_artifact",
    "observation_frame_seconds",
    "observations",
    "scenario_cycle_seconds",
    "schema",
    "seed",
    "start_at",
    "truth_artifact",
}
_ARTIFACT_KEYS: Final = {"digest", "format", "path", "schema"}


class ContractValidationError(ValueError):
    """A public benchmark document violates its closed versioned contract."""


def canonical_json_bytes(value: object) -> bytes:
    """Encode one public document using the v1 canonical JSON profile."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def document_digest(value: object) -> str:
    """Return a prefixed SHA-256 over canonical JSON bytes."""

    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _catalog_payload(catalog: Catalog) -> dict[str, object]:
    payload = {
        "loops": [asdict(item) for item in catalog.loops],
        "signals": [asdict(item) for item in catalog.signals],
        "scenarios": [asdict(item) for item in catalog.scenarios],
    }
    return json.loads(canonical_json_bytes(payload))


def build_benchmark_manifest(catalog: Catalog | None = None) -> dict[str, object]:
    """Build the complete deterministic manifest for the selected catalog."""

    selected = catalog or load_catalog()
    errors = selected.validate()
    if errors:
        raise ContractValidationError("invalid catalog: " + "; ".join(errors))
    model_errors = validate_model(selected)
    if model_errors:
        raise ContractValidationError("invalid model: " + "; ".join(model_errors))
    payload = _catalog_payload(selected)
    manifest: dict[str, object] = {
        "schema": BENCHMARK_MANIFEST_SCHEMA,
        "benchmark_version": BENCHMARK_VERSION,
        "namespace_uri": NAMESPACE_URI,
        "catalog_digest": f"sha256:{selected.digest}",
        **payload,
        "loop_models": [asdict(model_definition_for(loop)) for loop in selected.loops],
        "couplings": [asdict(item) for item in build_coupling_graph(selected)],
        "scenario_parameterizations": [
            {
                "scenario_id": scenario.scenario_id,
                "parameters": SCENARIO_PARAMETERS[scenario.scenario_id],
            }
            for scenario in selected.scenarios
        ],
        "runtime_profiles": [item.to_dict() for item in load_runtime_profiles()],
    }
    validate_benchmark_manifest(manifest)
    return manifest


def _catalog_from_manifest(manifest: dict[str, object]) -> Catalog:
    try:
        loops = tuple(LoopDefinition(**item) for item in manifest["loops"])
        signals = tuple(
            SignalDefinition(
                **{
                    **item,
                    "context_for_loop_ids": tuple(item["context_for_loop_ids"]),
                }
            )
            for item in manifest["signals"]
        )
        scenarios = tuple(
            ScenarioDefinition(
                **{
                    **item,
                    "primary_loop_ids": tuple(item["primary_loop_ids"]),
                }
            )
            for item in manifest["scenarios"]
        )
    except (KeyError, TypeError) as error:
        raise ContractValidationError("manifest catalog records have an invalid shape") from error
    return Catalog(loops=loops, signals=signals, scenarios=scenarios)


def validate_benchmark_manifest(
    value: object,
    *,
    expected_catalog_digest: str | None = None,
) -> dict[str, object]:
    """Validate the exact v1 manifest and return it unchanged."""

    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise ContractValidationError("benchmark manifest must have the exact v1 fields")
    if value["schema"] != BENCHMARK_MANIFEST_SCHEMA:
        raise ContractValidationError("unsupported benchmark manifest schema")
    version = value["benchmark_version"]
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ContractValidationError("benchmark_version must be canonical semantic versioning")
    if version != BENCHMARK_VERSION:
        raise ContractValidationError("benchmark version is incompatible")
    if value["namespace_uri"] != NAMESPACE_URI:
        raise ContractValidationError("benchmark namespace URI is incompatible")
    declared_digest = value["catalog_digest"]
    if not isinstance(declared_digest, str) or not DIGEST_PATTERN.fullmatch(declared_digest):
        raise ContractValidationError("catalog_digest must be a prefixed SHA-256")
    if expected_catalog_digest is not None and declared_digest != expected_catalog_digest:
        raise ContractValidationError("catalog digest does not match the required release")
    catalog = _catalog_from_manifest(value)
    errors = catalog.validate()
    if errors:
        raise ContractValidationError("invalid manifest catalog: " + "; ".join(errors))
    model_errors = validate_model(catalog)
    if model_errors:
        raise ContractValidationError("invalid manifest model: " + "; ".join(model_errors))
    if declared_digest != f"sha256:{catalog.digest}":
        raise ContractValidationError("catalog digest does not match manifest records")
    expected_models = [asdict(model_definition_for(loop)) for loop in catalog.loops]
    if value["loop_models"] != expected_models:
        raise ContractValidationError("loop model definitions are incompatible")
    expected_scenarios = [
        {
            "scenario_id": scenario.scenario_id,
            "parameters": SCENARIO_PARAMETERS[scenario.scenario_id],
        }
        for scenario in catalog.scenarios
    ]
    if value["scenario_parameterizations"] != expected_scenarios:
        raise ContractValidationError("scenario parameterizations are incompatible")
    profiles = value["runtime_profiles"]
    if not isinstance(profiles, list):
        raise ContractValidationError("runtime_profiles must be an array")
    try:
        typed_profiles = tuple(validate_runtime_profile(item) for item in profiles)
    except RuntimeProfileError as error:
        raise ContractValidationError("invalid runtime profile") from error
    if tuple(item.profile_id for item in typed_profiles) != (
        "development",
        "paper",
        "smoke",
        "stress",
    ):
        raise ContractValidationError("runtime profile set or ordering is incompatible")
    loop_ids = {item.loop_id for item in catalog.loops}
    couplings = value["couplings"]
    if not isinstance(couplings, list) or not couplings:
        raise ContractValidationError("couplings must be a non-empty array")
    identities: set[tuple[str, str, str]] = set()
    for item in couplings:
        if not isinstance(item, dict) or set(item) != {
            "delay_seconds",
            "gain",
            "mechanism",
            "source_loop_id",
            "target_loop_id",
        }:
            raise ContractValidationError("coupling must have the exact v1 fields")
        source = item["source_loop_id"]
        target = item["target_loop_id"]
        mechanism = item["mechanism"]
        if source not in loop_ids or target not in loop_ids or source == target:
            raise ContractValidationError("coupling references an invalid loop")
        if not isinstance(mechanism, str) or not mechanism:
            raise ContractValidationError("coupling mechanism must be non-empty")
        identity = (source, target, mechanism)
        if identity in identities:
            raise ContractValidationError("coupling identities must be unique")
        identities.add(identity)
        for field in ("gain", "delay_seconds"):
            number = item[field]
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ContractValidationError(f"coupling {field} must be numeric")
            if not math.isfinite(float(number)):
                raise ContractValidationError(f"coupling {field} must be finite")
        if float(item["delay_seconds"]) <= 0:
            raise ContractValidationError("coupling delay_seconds must be positive")
    return value


def load_benchmark_manifest(
    path: str | Path,
    *,
    expected_catalog_digest: str | None = None,
) -> dict[str, object]:
    """Load and validate a UTF-8 JSON manifest from an explicit path."""

    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractValidationError("benchmark manifest is unreadable") from error
    return validate_benchmark_manifest(value, expected_catalog_digest=expected_catalog_digest)


def write_benchmark_manifest(path: str | Path, manifest: object) -> str:
    """Validate and write canonical JSON, returning its document digest."""

    value = validate_benchmark_manifest(manifest)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(value) + b"\n")
    return document_digest(value)


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field} must be an ISO 8601 timestamp")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ContractValidationError(f"{field} must be an ISO 8601 timestamp") from error
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ContractValidationError(f"{field} must include a UTC offset")
    return stamp


def _positive_finite(value: object, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number <= minimum:
        raise ContractValidationError(f"{field} must be finite and greater than {minimum}")
    return number


def validate_dataset_manifest(value: object) -> dict[str, object]:
    """Validate the exact v1 dataset manifest and its compatibility fields."""

    if not isinstance(value, dict) or set(value) != _DATASET_MANIFEST_KEYS:
        raise ContractValidationError("dataset manifest must have the exact v1 fields")
    if value["schema"] != DATASET_MANIFEST_SCHEMA:
        raise ContractValidationError("unsupported dataset manifest schema")
    if value["benchmark_version"] != BENCHMARK_VERSION:
        raise ContractValidationError("dataset benchmark version is incompatible")
    for field in ("benchmark_manifest_digest", "catalog_digest"):
        digest = value[field]
        if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
            raise ContractValidationError(f"{field} must be a prefixed SHA-256")
    start = _aware_datetime(value["start_at"], "start_at")
    end = _aware_datetime(value["end_at"], "end_at")
    duration = _positive_finite(value["duration_seconds"], "duration_seconds")
    integration = _positive_finite(value["integration_step_seconds"], "integration_step_seconds")
    frame = _positive_finite(value["observation_frame_seconds"], "observation_frame_seconds")
    cycle = _positive_finite(value["scenario_cycle_seconds"], "scenario_cycle_seconds")
    if cycle < 600:
        raise ContractValidationError("scenario_cycle_seconds must be at least 600")
    if frame < integration or not math.isclose(
        frame / integration, round(frame / integration), abs_tol=1e-9
    ):
        raise ContractValidationError(
            "observation_frame_seconds must be an integer multiple of integration step"
        )
    if not math.isclose((end - start).total_seconds(), duration, abs_tol=1e-6):
        raise ContractValidationError("dataset timestamps do not match duration_seconds")
    for field, minimum in (("frames", 1), ("observations", 0)):
        count = value[field]
        if isinstance(count, bool) or not isinstance(count, int) or count < minimum:
            raise ContractValidationError(f"{field} must be an integer >= {minimum}")
    seed = value["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ContractValidationError("seed must be an integer")
    for field, expected_schema, expected_format in (
        ("observation_artifact", OBSERVATION_SCHEMA, "csv"),
        ("truth_artifact", TRUTH_FRAME_SCHEMA, "jsonl"),
    ):
        artifact = value[field]
        if not isinstance(artifact, dict) or set(artifact) != _ARTIFACT_KEYS:
            raise ContractValidationError(f"{field} must have the exact v1 fields")
        if artifact["schema"] != expected_schema or artifact["format"] != expected_format:
            raise ContractValidationError(f"{field} schema or format is incompatible")
        path = artifact["path"]
        digest = artifact["digest"]
        if (
            not isinstance(path, str)
            or not path
            or Path(path).name != path
            or not isinstance(digest, str)
            or not DIGEST_PATTERN.fullmatch(digest)
        ):
            raise ContractValidationError(f"{field} path or digest is invalid")
    return value


def write_dataset_manifest(path: str | Path, manifest: object) -> str:
    """Validate and write one canonical v1 dataset manifest."""

    value = validate_dataset_manifest(manifest)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(value) + b"\n")
    return document_digest(value)


__all__ = [
    "BENCHMARK_MANIFEST_SCHEMA",
    "BENCHMARK_VERSION",
    "DATASET_MANIFEST_SCHEMA",
    "NAMESPACE_URI",
    "OBSERVATION_SCHEMA",
    "TRUTH_FRAME_SCHEMA",
    "ContractValidationError",
    "build_benchmark_manifest",
    "canonical_json_bytes",
    "document_digest",
    "load_benchmark_manifest",
    "validate_benchmark_manifest",
    "validate_dataset_manifest",
    "write_benchmark_manifest",
    "write_dataset_manifest",
]
