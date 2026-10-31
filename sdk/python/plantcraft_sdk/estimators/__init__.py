"""Estimators over plant data (prototype, 2026-10-31, item E3.2 of the Saturday plan): Kalman
filters, a first-order-plus-dead-time fit to build their model, and soft sensors.

A filter or soft sensor turns signals a plant already measures into a better estimate of one
it measures badly (noisy, drifting) or not at all (a lab value between samples). Each is a pure
function over arrays: the app gives it series read through PlantCraft and writes the estimate
back as a derived signal. Models fits the model of a virtual sensor, Analytics runs the filters as
blocks (``estimator.*``), so both use this one copy (``apps/models/docs/estimators.md``). Nothing
here acts on the plant. NumPy only.
"""

from plantcraft_sdk.estimators.identify import Fopdt, fit_fopdt
from plantcraft_sdk.estimators.kalman import (
    Filtered,
    StateSpace,
    fopdt_model,
    kalman_filter,
    local_level,
    noise_variance,
    tune,
)
from plantcraft_sdk.estimators.softsensor import SoftSensor, fit_soft_sensor

__all__ = [
    "Filtered",
    "Fopdt",
    "SoftSensor",
    "StateSpace",
    "fit_fopdt",
    "fit_soft_sensor",
    "fopdt_model",
    "kalman_filter",
    "local_level",
    "noise_variance",
    "tune",
]
