"""A12: PI settings from a model fitted to the loop's own window (Lambda/IMC), read only."""

from __future__ import annotations

import numpy as np
import pandas as pd

from linkcraft.engine.tuning import suggest
from tests.conftest import client_for


def plant(n=2880, dt=10.0, gain=2.0, tau=120.0, delay=3, open_loop=True, seed=2):
    """A first order with dead time, driven by OP steps (open loop) or by a PI on SP steps."""

    rng = np.random.default_rng(seed)
    a = np.exp(-dt / tau)
    op = 20 + 5 * np.repeat(rng.choice([-1, 1], n // 60 + 1), 60)[:n]
    pv, x, integral = np.zeros(n), 0.0, 0.0
    sp = np.where((np.arange(n) // 300) % 2 == 0, 40.0, 50.0)
    for k in range(1, n):
        x = a * x + (1 - a) * gain * (op[max(0, k - delay)] - 20)
        pv[k] = 30 + x + rng.normal(0, 0.1)
        if not open_loop:
            error = sp[k] - pv[k]
            integral += error * dt / 150.0
            op[k] = np.clip(20 + 0.3 * (error + integral), 0, 100)
    return pd.DataFrame({"pv": pv, "op": op})


def test_an_open_loop_window_gives_the_model_and_lambda_settings():
    found = suggest(plant(), 10.0)
    assert found["available"] and found["reliable"], found
    model = found["model"]
    assert abs(model["gain"] - 2.0) < 0.1 and abs(model["tau_seconds"] - 120) < 15
    assert found["action"] == "reverse"
    tight, moderate, robust = found["settings"]
    assert [item["choice"] for item in found["settings"]] == ["tight", "moderate", "robust"]
    # Kc = tau / (K (lambda + theta)): the slower the closed loop, the smaller the gain.
    assert tight["kc"] > moderate["kc"] > robust["kc"] > 0
    expected = model["tau_seconds"] / (
        model["gain"] * (moderate["lambda_seconds"] + model["dead_time_seconds"])
    )
    assert abs(moderate["kc"] - expected) < 1e-3
    assert moderate["ti_seconds"] == model["tau_seconds"]


def test_a_closed_loop_window_still_finds_the_gain():
    found = suggest(plant(open_loop=False), 10.0)
    assert found["available"]
    assert abs(found["model"]["gain"] - 2.0) < 0.2


def test_no_suggestion_without_movement_or_data():
    still = pd.DataFrame({"pv": np.full(500, 3.0), "op": np.full(500, 40.0)})
    assert suggest(still, 10.0)["available"] is False
    assert suggest(pd.DataFrame(), 10.0)["available"] is False
    assert suggest(plant().iloc[:30], 10.0)["available"] is False


def test_the_loop_page_asks_for_a_suggestion(analysed, fake):
    with client_for(analysed, fake, "operator") as client:
        found = client.get("/link/api/loops/fic-101/tuning")
        assert found.status_code == 200, found.text
        body = found.json()
        assert "available" in body and body["source_end"]
        if body["available"]:
            assert len(body["settings"]) == 3
        assert client.get("/link/api/loops/nope/tuning").status_code == 404
