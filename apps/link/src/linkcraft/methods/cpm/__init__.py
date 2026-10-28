"""CPM methodology blocks, in the order they appear in the catalog."""

from linkcraft.methods.cpm import (
    attenuation,
    error_metrics,
    harris,
    interaction_correlation,
    interventions,
    manual_mode,
    operating_band,
    oscillation,
    sampling_quality,
    saturation,
    sensor_noise,
    setpoint_activity,
    stiction,
    valve_travel,
    variability,
)

METHOD_MODULES = [
    error_metrics,
    interventions,
    attenuation,
    operating_band,
    sampling_quality,
    variability.pv_variability,
    manual_mode,
    saturation,
    setpoint_activity,
    oscillation,
    sensor_noise,
    valve_travel,
    stiction,
    interaction_correlation,
    harris.harris_index,
]

__all__ = ["METHOD_MODULES"]
