"""Human-readable labels shared by the API and persistence services."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from linkcraft.i18n import t


class TranslatedLabels(dict):
    """English labels that read back in the current request's language.

    The values are English constants (the catalog keys); ``labels[key]``,
    ``labels.get(key)``, ``values()`` and ``items()`` translate them when read,
    so a module-level dict still answers in the language of each request.
    """

    def __getitem__(self, key: Any) -> str:
        return t(dict.__getitem__(self, key))

    def get(self, key: Any, default: Any = None) -> Any:
        return t(dict.__getitem__(self, key)) if key in self else default

    def values(self) -> list[str]:  # type: ignore[override]
        return [t(value) for value in dict.values(self)]

    def items(self) -> list[tuple[Any, str]]:  # type: ignore[override]
        return [(key, t(value)) for key, value in dict.items(self)]


METHOD_LABELS = TranslatedLabels(
    {
        "error_metrics_basic": "PV–SP error",
        "pv_variability": "PV variability",
        "op_saturation_fraction": "Output saturation",
        "op_travel_reversal": "Valve travel",
        "oscillation_autocorrelation": "Oscillation",
        "sensor_noise_ratio": "Sensor noise",
        "stiction_screening": "Stiction screening",
        "harris_index": "Minimum-variance index",
        "manual_mode_fraction": "Manual mode",
        "setpoint_activity": "SP activity",
        "interaction_cross_correlation": "Loop interaction",
        "operational_interventions": "Operator interventions",
        "disturbance_attenuation": "Disturbance attenuation",
        "operating_band_fraction": "Time in operating band",
        "sampling_quality": "Sampling quality",
        "dq_availability": "Signal availability",
        "dq_value_integrity": "Value integrity",
        "dq_statistics": "Descriptive statistics",
    }
)

# Name and help for each method parameter, shown wherever a parameter is edited.
# A Field's own ``title``/``description`` (methods written with @method) wins.
PARAMETER_LABELS = {
    "error_tolerance": (
        "Error tolerance",
        "Mean absolute error, in the PV's unit, that scores zero. Empty: a share of the loop's "
        "scale (relative tolerance).",
    ),
    "acceptable_band": (
        "Acceptable band",
        "PV–SP deviation, in the PV's unit, considered satisfactory. Empty: a share of the "
        "loop's scale (relative band).",
    ),
    "relative_tolerance_percent": (
        "Relative tolerance (%)",
        "Mean absolute error, as a percentage of the PV span or the setpoint, that scores zero.",
    ),
    "relative_band_percent": (
        "Relative band (%)",
        "Satisfactory PV–SP deviation as a percentage of the PV span or the setpoint.",
    ),
    "pv_span": (
        "PV span",
        "Engineering span of the PV; when set, the relative tolerance is a share of it instead "
        "of the setpoint.",
    ),
    "assume_surge_level": (
        "Assume a surge level",
        "Run on a loop whose asset record gives no loop type (Surge level algorithm).",
    ),
    "sp_change_threshold": ("Minimum SP change", "Smallest SP move counted as an intervention."),
    "reference_hours": (
        "Reference window (h)",
        "Period used to normalize the number of interventions.",
    ),
    "full_performance_max": (
        "Interventions for full score",
        "Up to this total, the criterion scores 100%.",
    ),
    "zero_performance_min": (
        "Interventions for zero score",
        "From this total on, the criterion scores 0%.",
    ),
    "pv_range": ("PV range", "Engineering span used to normalize the PV."),
    "op_range": ("OP range", "Engineering span used to normalize the output."),
    "full_performance_factor": (
        "Factor for full score",
        "Amplification factor that represents good attenuation.",
    ),
    "zero_performance_factor": (
        "Factor for zero score",
        "Amplification factor that represents inadequate attenuation.",
    ),
    "movement_epsilon": ("Minimum movement", "Minimum movement to avoid an unstable ratio."),
    "lower_limit": ("Lower limit", "Lower limit of the operating band."),
    "upper_limit": ("Upper limit", "Upper limit of the operating band."),
    "margin": ("Margin", "Margin added to the configured limits."),
    "recommended_sample_seconds": (
        "Recommended sampling (s)",
        "Sampling interval suited to this loop function.",
    ),
    "gap_multiplier": (
        "Gap threshold",
        "Multiple of the sampling period from which an interval counts as a gap.",
    ),
    "variability_tolerance": (
        "Variability tolerance",
        "Reference standard deviation for a 100% score.",
    ),
    "manual_labels": ("Manual mode states", "Mode signal texts that mean manual operation."),
    "warning_fraction": (
        "Warning fraction",
        "Fraction of the window in manual from which the method warns.",
    ),
    "change_threshold": ("Minimum SP change", "Smallest SP move counted as a change."),
    "max_changes_per_hour": (
        "Acceptable changes per hour",
        "Above this rate of SP changes the criterion loses score.",
    ),
    "min_lag_samples": (
        "Minimum lag (samples)",
        "Smallest autocorrelation lag considered when searching for the period.",
    ),
    "max_lag_samples": (
        "Maximum lag (samples)",
        "Largest lag considered; empty uses half the window.",
    ),
    "min_cycles": (
        "Minimum cycles",
        "Minimum number of cycles in the window to assert oscillation.",
    ),
    "min_autocorrelation": (
        "Minimum autocorrelation",
        "Autocorrelation peak from which oscillation is considered.",
    ),
    "min_regularity": (
        "Minimum regularity",
        "Regularity of the period (mean over three standard deviations of the periods between "
        "autocorrelation zero crossings) from which an oscillation is sustained.",
    ),
    "noise_ratio_threshold": (
        "Noise ratio threshold",
        "Share of PV variation attributed to noise from which the method warns.",
    ),
    "noise_abs_tolerance": (
        "Tolerated absolute noise",
        "Noise amplitude accepted without penalizing the score.",
    ),
    "max_travel_per_hour": (
        "Acceptable travel per hour (%)",
        "Accumulated valve movement per hour above which it wears.",
    ),
    "max_reversals_per_hour": (
        "Acceptable reversals per hour",
        "Valve direction changes per hour above which the criterion loses score.",
    ),
    "reversal_epsilon": (
        "Minimum reversal movement",
        "Smallest output movement counted as a direction change.",
    ),
    "jump_threshold": (
        "Minimum OP jump",
        "Sudden OP change that marks a slip after the valve sticks.",
    ),
    "jump_fraction_reference": (
        "Reference jump fraction",
        "Share of stick-then-slip moves at which the slip part of the stiction score is full.",
    ),
    "correlation_threshold": (
        "Minimum correlation",
        "Cross-correlation from which two loops are considered to interact.",
    ),
    "max_gap_seconds": (
        "Maximum gap (s)",
        "Maximum interval between samples before it counts as missing data.",
    ),
    "min_coverage": ("Minimum coverage", "Minimum PV coverage for the data to be usable."),
    "frozen_fraction_limit": (
        "Maximum frozen fraction",
        "Maximum fraction of the window with the PV stuck at the same value.",
    ),
    "invalid_fraction_limit": (
        "Maximum invalid fraction",
        "Maximum fraction of invalid samples (text, infinity, empty).",
    ),
    "window_samples": ("Window (samples)", "Samples in the average."),
    "time_constant_seconds": ("Time constant (s)", "Filter time constant."),
    "gain": ("Gain", "Multiplies the signal."),
    "offset": ("Offset", "Added after the gain."),
    "lower": ("Lower limit", "Lower limit."),
    "upper": ("Upper limit", "Upper limit."),
    "samples": ("Delay (samples)", "Delay in samples."),
}


def parameter_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A parameters model's JSON schema with names and help in the current language.

    The labels above apply to the platform's own methods and blocks; a method
    from the method folder keeps the ``title``/``description`` its author gave.
    """

    schema = model.model_json_schema()
    platform_model = model.__module__.startswith("linkcraft.")
    for key, prop in schema.get("properties", {}).items():
        field = model.model_fields.get(key)
        title, help_text = PARAMETER_LABELS.get(key, (None, None))
        authored = field is not None and not platform_model
        if title and not (authored and field.title):
            prop["title"] = t(title)
        elif prop.get("title"):
            prop["title"] = t(prop["title"])
        if help_text and not (authored and field.description):
            prop["description"] = t(help_text)
        elif prop.get("description"):
            prop["description"] = t(prop["description"])
    return schema
