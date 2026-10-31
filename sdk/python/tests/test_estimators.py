"""Estimators (prototype, E3.2): the Kalman filter, the FOPDT fit and the soft sensor, on a
plant made here (a first order with dead time, a noisy sensor, a drifting one)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from plantcraft_sdk.estimators import (
    fit_fopdt,
    fit_soft_sensor,
    fopdt_model,
    kalman_filter,
    local_level,
    tune,
)
from plantcraft_sdk.estimators.kalman import noise_variance

DT = 5.0


def plant(steps: int = 4000, noise: float = 0.03, drift: float = 0.0, seed: int = 7):
    rng = np.random.default_rng(seed)
    u = 0.5 + 0.1 * np.sign(np.sin(np.arange(steps) / 60.0)) + 0.01 * rng.standard_normal(steps)
    a, gain, dead = math.exp(-DT / 60.0), 0.8, 4
    x = np.zeros(steps)
    for k in range(1, steps):
        drive = u[k - 1 - dead] if k - 1 - dead >= 0 else u[0]
        x[k] = a * x[k - 1] + gain * (1 - a) * (drive - 0.5) + 2e-4 * rng.standard_normal()
    true = 0.4 + x
    bias = drift * np.clip(np.arange(steps) - steps // 2, 0, None) / steps
    measured = true + bias + noise * rng.standard_normal(steps)
    return u, true, measured, bias


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def test_fopdt_fit_finds_gain_time_constant_and_dead_time():
    u, true, _measured, _bias = plant(noise=0.0)
    fit = fit_fopdt(u, true, DT, max_dead=10)
    assert fit.gain == pytest.approx(0.8, rel=0.05)
    assert fit.tau == pytest.approx(60.0, rel=0.1)
    assert fit.dead_steps == 4
    assert fit.r2 > 0.95


def test_noise_variance_from_the_series_alone():
    _u, _true, measured, _bias = plant(noise=0.03)
    assert noise_variance(measured) == pytest.approx(0.03**2, rel=0.15)


def test_the_model_based_filter_beats_the_raw_sensor_without_lag():
    u, true, measured, _bias = plant(noise=0.03)
    fit = fit_fopdt(u, true, DT, max_dead=10)
    r = noise_variance(measured)
    _q, out = tune(lambda q: fopdt_model(fit, q, r), measured, u)
    assert rmse(out.estimate, true) < rmse(measured, true) / 5
    plain_q, plain = tune(lambda q: local_level(q, r), measured)
    assert plain_q > 0
    assert rmse(plain.estimate, true) < rmse(measured, true)


def test_a_gap_is_bridged_by_the_model():
    u, true, measured, _bias = plant(noise=0.03)
    fit = fit_fopdt(u, true, DT, max_dead=10)
    gappy = measured.copy()
    gappy[1500:2100] = np.nan  # 50 minutes without the sensor
    out = kalman_filter(fopdt_model(fit, 1e-6, noise_variance(measured)), gappy, u)
    assert np.isfinite(out.estimate).all()
    assert np.isnan(out.innovations[1500:2100]).all()
    assert rmse(out.estimate[1500:2100], true[1500:2100]) < 0.03


def test_the_bias_state_tracks_a_drifting_sensor():
    u, true, measured, bias = plant(noise=0.01, drift=0.2)
    fit = fit_fopdt(u[:1500], true[:1500], DT, max_dead=10)
    out = kalman_filter(
        fopdt_model(fit, 1e-7, noise_variance(measured), bias=True, q_bias=1e-7), measured, u
    )
    assert rmse(out.states[0] + fit.y0, true) < rmse(measured, true) / 3
    assert rmse(out.states[1], bias) < 0.02


def test_soft_sensor_from_sparse_samples():
    u, true, measured, _bias = plant(noise=0.02)
    lab = np.full_like(measured, np.nan)
    lab[::40] = measured[::40]
    half = len(u) // 2
    sensor = fit_soft_sensor(u[:half], lab[:half], lags=[0, 4, 8, 16, 32], alpha=1.0)
    predicted = sensor.predict(u)
    held = np.where(np.isfinite(lab), lab, np.nan)
    for k in range(1, len(held)):
        if not math.isfinite(held[k]):
            held[k] = held[k - 1]
    test = slice(half + 40, None)
    assert rmse(predicted[test], true[test]) < rmse(held[test], true[test])


def test_too_few_samples_are_refused():
    with pytest.raises(ValueError):
        fit_soft_sensor(np.ones(6), np.ones(6), lags=[0, 1, 2])
    with pytest.raises(ValueError):
        fit_fopdt(np.ones(5), np.ones(5), DT)
