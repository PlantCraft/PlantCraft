"""Versioned runtime profiles for reproducible benchmark operation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from importlib.resources import files
from typing import Final

RUNTIME_PROFILE_SCHEMA: Final = "process-plant-opcua/runtime-profile/v1"
PROFILE_IDS: Final = ("development", "paper", "smoke", "stress")
_PROFILE_KEYS: Final = {
    "description",
    "duration_seconds",
    "history_seconds",
    "integration_step_seconds",
    "max_history_values_per_node",
    "observation_frame_seconds",
    "profile_id",
    "scenario_cycle_seconds",
    "schema",
}


class RuntimeProfileError(ValueError):
    """A runtime profile does not satisfy the public v1 contract."""


@dataclass(frozen=True)
class RuntimeProfile:
    schema: str
    profile_id: str
    description: str
    duration_seconds: int
    integration_step_seconds: float
    observation_frame_seconds: float
    scenario_cycle_seconds: float
    history_seconds: int
    max_history_values_per_node: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeProfileError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise RuntimeProfileError(f"{field} must be finite and positive")
    return number


def validate_runtime_profile(value: object) -> RuntimeProfile:
    """Return a typed profile only when the closed v1 shape is valid."""

    if not isinstance(value, dict) or set(value) != _PROFILE_KEYS:
        raise RuntimeProfileError("runtime profile must have the exact v1 fields")
    if value["schema"] != RUNTIME_PROFILE_SCHEMA:
        raise RuntimeProfileError("unsupported runtime profile schema")
    profile_id = value["profile_id"]
    description = value["description"]
    if not isinstance(profile_id, str) or not profile_id:
        raise RuntimeProfileError("profile_id must be a non-empty string")
    if not isinstance(description, str) or not description:
        raise RuntimeProfileError("description must be a non-empty string")
    duration = _positive_number(value["duration_seconds"], "duration_seconds")
    integration = _positive_number(value["integration_step_seconds"], "integration_step_seconds")
    frame = _positive_number(value["observation_frame_seconds"], "observation_frame_seconds")
    cycle = _positive_number(value["scenario_cycle_seconds"], "scenario_cycle_seconds")
    history = _positive_number(value["history_seconds"], "history_seconds")
    maximum = _positive_number(value["max_history_values_per_node"], "max_history_values_per_node")
    if not math.isclose(duration / frame, round(duration / frame), abs_tol=1e-9):
        raise RuntimeProfileError("duration_seconds must be divisible by frame seconds")
    if frame < integration or not math.isclose(
        frame / integration, round(frame / integration), abs_tol=1e-9
    ):
        raise RuntimeProfileError(
            "observation_frame_seconds must be an integer multiple of integration step"
        )
    if cycle < 600:
        raise RuntimeProfileError("scenario_cycle_seconds must be at least 600")
    for field in ("duration_seconds", "history_seconds", "max_history_values_per_node"):
        if isinstance(value[field], bool) or not isinstance(value[field], int):
            raise RuntimeProfileError(f"{field} must be an integer")
    return RuntimeProfile(
        schema=RUNTIME_PROFILE_SCHEMA,
        profile_id=profile_id,
        description=description,
        duration_seconds=int(duration),
        integration_step_seconds=integration,
        observation_frame_seconds=frame,
        scenario_cycle_seconds=cycle,
        history_seconds=int(history),
        max_history_values_per_node=int(maximum),
    )


def load_runtime_profiles() -> tuple[RuntimeProfile, ...]:
    """Load the exact built-in runtime-profile set in stable identifier order."""

    root = files(__package__).joinpath("profiles", "v1")
    profiles = []
    for profile_id in PROFILE_IDS:
        payload = json.loads(root.joinpath(f"{profile_id}.json").read_text(encoding="utf-8"))
        profile = validate_runtime_profile(payload)
        if profile.profile_id != profile_id:
            raise RuntimeProfileError("runtime profile filename and identifier differ")
        profiles.append(profile)
    return tuple(profiles)


def get_runtime_profile(profile_id: str) -> RuntimeProfile:
    """Return one exact built-in profile or fail without selecting a fallback."""

    for profile in load_runtime_profiles():
        if profile.profile_id == profile_id:
            return profile
    raise RuntimeProfileError(f"unknown runtime profile: {profile_id}")


__all__ = [
    "PROFILE_IDS",
    "RUNTIME_PROFILE_SCHEMA",
    "RuntimeProfile",
    "RuntimeProfileError",
    "get_runtime_profile",
    "load_runtime_profiles",
    "validate_runtime_profile",
]
