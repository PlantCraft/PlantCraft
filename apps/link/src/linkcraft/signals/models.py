"""What a signal's quality may hold, without the database: its states, the settings a signal
takes, the roles that are constant by design and the algorithm's settings (PlantCraft
``docs/app-standard.md``, section 5: the routers validate with these, the stores keep them)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

STATUSES = ("good", "suspect", "bad", "unknown")
SETTING_KEYS = (
    "low",
    "high",
    "reference",
    "checks_off",
    "checks_on",
    "parameters",
    # "lab" or "continuous"; unset, a signal from a CSV file is sampled (laboratory analyses).
    "sampling",
    # A sampled signal's expected interval between samples; unset, read from its samples.
    "sample_interval_minutes",
)


# Signal roles (PlantCraft assets) whose signals are constant by design: the
# frozen value check is off for them unless a person switches it on. A controller output
# held still is the loop's state (saturated valve, manual mode), which the loop methods
# judge; calling it bad data would hide the very fault they report.
CONSTANT_ROLES = ("sp", "mode", "op")


class SignalQualitySettings(BaseModel):
    """The Signal quality algorithm (admins edit it; its schedule holds when it runs)."""

    window_hours: float = Field(default=24.0, gt=0.0, le=31 * 24)
    # Checks that run by default (a signal can switch one off or on for itself).
    enabled_checks: list[str] | None = None
    # Default parameters per check, over the check's own defaults.
    check_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
