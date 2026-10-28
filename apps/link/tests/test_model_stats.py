"""Residual statistics against values computed by hand and from public tables."""

from __future__ import annotations

import numpy as np
import pytest

from linkcraft.models.stats import Calibration, calibrate, chi2_quantile, judge, positive_definite

# Chi-square quantiles from any statistics table (NIST/SEMATECH e-Handbook, 1.3.6.7.4).
TABLE = [
    (0.95, 1, 3.841),
    (0.99, 1, 6.635),
    (0.95, 2, 5.991),
    (0.99, 2, 9.210),
    (0.99, 3, 11.345),
    (0.99, 5, 15.086),
    (0.95, 10, 18.307),
    (0.999, 4, 18.467),
]


@pytest.mark.parametrize(("confidence", "dof", "expected"), TABLE)
def test_chi2_quantile_matches_the_table(confidence, dof, expected):
    assert chi2_quantile(confidence, dof) == pytest.approx(expected, abs=0.001)


def test_chi2_quantile_refuses_nonsense():
    with pytest.raises(ValueError):
        chi2_quantile(1.0, 2)
    with pytest.raises(ValueError):
        chi2_quantile(0.99, 0)


def _normal(rows=2000, seed=1):
    rng = np.random.default_rng(seed)
    cov = np.array([[1.0, 0.6], [0.6, 2.0]])
    return rng.multivariate_normal([0.0, 0.0], cov, size=rows), cov


def test_calibration_recovers_mean_and_covariance():
    rows, cov = _normal()
    found = calibrate(rows, ["a", "b"])
    assert np.allclose(found.cov, cov, atol=0.15)
    assert np.allclose(found.mean, [0, 0], atol=0.1)
    assert found.samples > 1900 and found.std[1] == pytest.approx(np.sqrt(2), rel=0.05)


def test_calibration_leaves_out_a_short_upset_and_says_so():
    rows, _ = _normal()
    rows[:100, 0] = 40.0
    found = calibrate(rows, ["a", "b"])
    assert found.std[0] < 1.2
    assert any("left out" in warning for warning in found.warnings)


def test_calibration_warns_when_a_residual_sits_far_from_zero():
    rows, _ = _normal()
    rows[:, 1] += 9.0
    found = calibrate(rows, ["a", "b"])
    assert any(warning.startswith("b:") for warning in found.warnings)


def test_calibration_needs_enough_clean_rows():
    rows = np.full((50, 2), np.nan)
    rows[:10] = 0.1
    with pytest.raises(ValueError, match="at least"):
        calibrate(rows, ["a", "b"])


def test_normal_operation_stays_mostly_below_the_limit():
    rows, _ = _normal()
    calibration = calibrate(rows, ["a", "b"])
    fresh, _ = _normal(seed=7)
    found = judge(fresh, calibration, confidence=0.99)
    assert found.exceed_share == pytest.approx(0.01, abs=0.01)


def test_contributions_add_up_and_point_at_the_shifted_output():
    rows, _ = _normal()
    calibration = calibrate(rows, ["a", "b"])
    shifted, _ = _normal(rows=200, seed=3)
    shifted[:, 1] += 8.0
    found = judge(shifted, calibration)
    assert found.exceed_share > 0.9
    assert sum(found.contributions.values()) == pytest.approx(100.0)
    assert found.contributions["b"] > 80
    assert found.outputs["b"]["mean"] == pytest.approx(8.0, abs=0.5)
    # T² equals the sum of every term (rᵀ S⁻¹ r).
    r = shifted[0]
    assert found.t2[0] == pytest.approx(r @ np.linalg.inv(np.array(calibration.cov)) @ r)


def test_missing_samples_are_not_judged():
    calibration = Calibration(["a"], [0.0], [[1.0]], 100)
    found = judge(np.array([[np.nan], [0.1], [10.0]]), calibration)
    assert np.isnan(found.t2[0]) and found.exceed_share == pytest.approx(0.5)


def test_collinear_outputs_still_invert():
    matrix = positive_definite(np.array([[1.0, 1.0], [1.0, 1.0]]))
    assert np.all(np.linalg.eigvalsh(matrix) > 0)
    np.linalg.inv(matrix)
