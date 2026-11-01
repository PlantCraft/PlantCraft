"""A10: overshoot, rise and settling times and IAE of the setpoint steps found in the window."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from linkcraft.engine.step_response import step_responses
from tests.conftest import client_for

DT = 1.0


def second_order(t, zeta=0.5, wn=0.1):
    """The unit step response of a second order: 1 - e^(-zeta wn t)(cos wd t + ...)."""

    wd = wn * math.sqrt(1 - zeta**2)
    decay = np.exp(-zeta * wn * t)
    return 1 - decay * (np.cos(wd * t) + zeta / math.sqrt(1 - zeta**2) * np.sin(wd * t))


def window(steps=((200, 50.0, 60.0), (600, 60.0, 55.0)), n=1000, zeta=0.5, noise=0.0, seed=1):
    """SP held at 50, stepped as listed, and a PV answering each step as a second order."""

    sp = np.full(n, steps[0][1])
    pv = np.full(n, steps[0][1])
    for at, before, after in steps:
        sp[at:] = after
        t = np.arange(n - at) * DT
        pv[at:] = before + (after - before) * second_order(t, zeta)
    pv = pv + np.random.default_rng(seed).normal(0, noise, n)
    index = pd.date_range("2026-10-31", periods=n, freq="1s", tz="UTC")
    return pd.DataFrame({"sp": sp, "pv": pv}, index=index)


def test_the_figures_of_a_known_second_order():
    found = step_responses(window(), DT)
    assert found["available"], found
    up, down = found["steps"]
    # Overshoot of a second order: exp(-pi zeta / sqrt(1 - zeta^2)) = 16.3 % at zeta 0.5.
    expected = 100 * math.exp(-math.pi * 0.5 / math.sqrt(0.75))
    assert abs(up["overshoot_pct"] - expected) < 0.5 and abs(down["overshoot_pct"] - expected) < 0.5
    assert up["size"] == 10.0 and down["size"] == -5.0
    # Rise 10-90 % of a zeta 0.5 second order is about 1.64 / wn = 16.4 s.
    assert 14 <= up["rise_seconds"] <= 19
    # Settling to 5 %: about 3 / (zeta wn) = 60 s (the envelope; the response settles a bit sooner).
    assert 40 <= up["settling_seconds"] <= 65 and up["settled"]
    # IAE per unit of step: the same shape answers the same, whatever the size.
    assert abs(up["iae_seconds"] - down["iae_seconds"]) < 0.5
    assert found["summary"]["steps"] == 2 and found["summary"]["settled_pct"] == 100.0
    assert up["at"] == "2026-10-31T00:03:20Z"


def test_a_well_damped_loop_does_not_overshoot_and_a_slow_one_does_not_settle():
    calm = step_responses(window(zeta=0.95), DT)["steps"][0]
    assert calm["overshoot_pct"] < 1.0
    slow = window(steps=((900, 50.0, 60.0),))
    slow["pv"] = 50.0 + 10.0 * (1 - np.exp(-np.clip(np.arange(1000) - 900, 0, None) / 200.0))
    late = step_responses(slow, DT)["steps"][0]
    assert late["settled"] is False and late["settling_seconds"] is None
    assert late["reached"] is False and late["rise_seconds"] is None


def test_noise_small_steps_and_manual_are_left_out():
    noisy = window(noise=0.05)
    found = step_responses(noisy, DT)
    assert found["available"] and len(found["steps"]) == 2
    assert abs(found["steps"][0]["overshoot_pct"] - 16.3) < 2.0
    tiny = window(steps=((200, 50.0, 50.1),), noise=0.05)
    assert step_responses(tiny, DT)["available"] is False
    manual = window()
    manual["mode"] = ["auto"] * 600 + ["MAN"] * 400
    found = step_responses(manual, DT)
    assert len(found["steps"]) == 1 and found["skipped"]["manual"] == 1


def test_a_short_ramp_is_one_step():
    ramped = window(steps=((200, 50.0, 60.0),))
    ramped.loc[ramped.index[200], "sp"] = 53.0
    ramped.loc[ramped.index[201], "sp"] = 57.0
    found = step_responses(ramped, DT)
    assert len(found["steps"]) == 1 and found["steps"][0]["size"] == 10.0


def test_nothing_to_measure():
    assert step_responses(pd.DataFrame(), DT)["available"] is False
    still = pd.DataFrame({"sp": np.full(300, 5.0), "pv": np.full(300, 5.0)})
    assert step_responses(still, DT)["available"] is False
    assert step_responses(pd.DataFrame({"pv": [1.0] * 50}), DT)["available"] is False


def test_the_loop_page_asks_for_the_step_responses(analysed, fake):
    with client_for(analysed, fake, "operator") as client:
        found = client.get("/link/api/loops/fic-101/step-response")
        assert found.status_code == 200, found.text
        body = found.json()
        assert "available" in body and body["source_end"]
        if body["available"]:
            assert body["steps"] and "overshoot_pct" in body["summary"]
        assert client.get("/link/api/loops/nope/step-response").status_code == 404
