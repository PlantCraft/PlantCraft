"""The synthetic oracle: process-like signals with one known fault injected each.

Five clean process shapes (a controlled flow, a slow temperature, a level with
setpoint moves, a ramping signal and a fast noisy pressure) times nine
conditions (clean, frozen, spikes, gap, stale, out of range, noisy,
quantised, drift against a reference), with two seeds each: 90 cases. Every
case carries the truth it was built with, so the oracle measures both
detection (the fault's check flags it) and false alarms (a clean signal stays
good). Fault sizes are set where a person would want to hear about them,
not at the edge of the thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SAMPLE_SECONDS = 10
COUNT = 24 * 3600 // SAMPLE_SECONDS
INDEX = pd.date_range("2026-10-01", periods=COUNT, freq=f"{SAMPLE_SECONDS}s")
LOW, HIGH = 0.0, 100.0
SHAPES = ("flow", "temperature", "level", "ramp", "pressure")
FAULTS = (
    "clean",
    "frozen",
    "spikes",
    "gap",
    "stale",
    "out_of_range",
    "noisy",
    "quantised",
    "drift",
)
# The check that must flag each fault (warning or bad).
DETECTED_BY = {
    "frozen": "sq_frozen",
    "spikes": "sq_spikes",
    "gap": "sq_availability",
    "stale": "sq_freshness",
    "out_of_range": "sq_range",
    "noisy": "sq_noise",
    "quantised": "sq_resolution",
    "drift": "sq_drift",
}
SEEDS = (1, 2)


@dataclass
class Case:
    name: str
    shape: str
    fault: str
    values: pd.Series
    reference: pd.Series | None = None
    truth: dict = field(default_factory=dict)


def clean(shape: str, rng: np.random.Generator) -> pd.Series:
    steps = np.arange(COUNT)
    if shape == "flow":
        walk = np.cumsum(rng.normal(0, 0.05, COUNT))
        values = (
            60
            + walk
            - np.convolve(walk, np.ones(720) / 720, mode="same")
            + rng.normal(0, 0.6, COUNT)
        )
    elif shape == "temperature":
        values = (
            45
            + 6 * np.sin(2 * np.pi * steps / 8640 + rng.uniform(0, 6))
            + rng.normal(0, 0.15, COUNT)
        )
    elif shape == "level":
        setpoint = np.repeat(rng.choice([40, 50, 60], size=8), COUNT // 8 + 1)[:COUNT]
        lagged = pd.Series(setpoint.astype(float)).ewm(span=60).mean().to_numpy()
        values = lagged + rng.normal(0, 0.4, COUNT)
    elif shape == "ramp":
        values = 30 + 25 * steps / COUNT + rng.normal(0, 0.3, COUNT)
    else:
        values = 70 + 1.5 * np.sin(2 * np.pi * steps / 400) + rng.normal(0, 0.8, COUNT)
    return pd.Series(values, index=INDEX)


def inject(
    fault: str, values: pd.Series, rng: np.random.Generator
) -> tuple[pd.Series, pd.Series | None]:
    values = values.copy()
    reference = None
    at = int(rng.integers(COUNT // 5, COUNT // 2))
    if fault == "frozen":
        length = int(rng.integers(3 * 360, 8 * 360))  # 3 to 8 hours
        values.iloc[at : at + length] = values.iloc[at]
    elif fault == "spikes":
        spread = float(values.quantile(0.99) - values.quantile(0.01))
        where = rng.choice(COUNT, size=int(rng.integers(3, 12)), replace=False)
        values.iloc[where] += (
            rng.choice([-1, 1], size=where.size) * rng.uniform(0.3, 0.6) * max(spread, 10.0)
        )
        values = values.clip(LOW - 1, HIGH + 1)
    elif fault == "gap":
        length = int(rng.integers(3 * 360, 6 * 360))  # 3 to 6 hours missing
        values = values.drop(values.index[at : at + length])
    elif fault == "stale":
        values = values.iloc[: COUNT - int(rng.integers(3 * 360, 6 * 360))]
    elif fault == "out_of_range":
        values.iloc[at : at + 2000] = HIGH + rng.uniform(5, 20) + rng.normal(0, 0.5, 2000)
    elif fault == "noisy":
        values = values + rng.normal(0, rng.uniform(4, 8), COUNT)
    elif fault == "quantised":
        quantum = float(values.std()) * rng.uniform(0.8, 1.5)
        values = (values / quantum).round() * quantum
    elif fault == "drift":
        reference = values + rng.normal(0, 0.1, COUNT)
        values = values + np.linspace(0, rng.uniform(6, 12), COUNT)
    return values, reference


def cases() -> list[Case]:
    found = []
    for shape in SHAPES:
        for fault in FAULTS:
            for seed in SEEDS:
                rng = np.random.default_rng(_seed(shape, fault, seed))
                values, reference = inject(fault, clean(shape, rng), rng)
                found.append(
                    Case(
                        name=f"{shape}-{fault}-{seed}",
                        shape=shape,
                        fault=fault,
                        values=values,
                        reference=reference,
                        truth={"detected_by": DETECTED_BY.get(fault)},
                    )
                )
    return found


def _seed(shape: str, fault: str, seed: int) -> int:
    return SHAPES.index(shape) * 1000 + FAULTS.index(fault) * 10 + seed
