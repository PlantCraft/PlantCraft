"""A PI tuning suggestion from the loop's recorded data: Lambda (IMC) rules on a fitted model.

The loop's own window gives a first order plus dead time from the controller output to the PV
(``plantcraft_sdk.estimators.fit_fopdt``). Lambda tuning (Dahlin 1968; Rivera, Morari and
Skogestad 1986; the SIMC variant of Skogestad 2003) then sets a PI controller for a chosen
closed-loop time constant lambda:

    Kc = tau / (K (lambda + theta)),  Ti = min(tau, 4 (lambda + theta))

Three choices are shown: tight (lambda = theta), moderate (lambda = tau) and robust
(lambda = 3 tau). Read only: nothing here writes to the controller (A12 of the 0.6 list).

Closed-loop data is a weak experiment: the controller makes the OP follow the PV, so the fit is
only as good as the OP movements that were not answers to the PV (setpoint changes, manual
moves). ``reliable`` says whether the fit explains the PV and the OP moved enough.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.estimators import fit_fopdt

# The fit must explain this share of the PV's variance, and the OP must move this share of
# its range (standard deviation), for the suggestion to be called reliable.
MIN_R2 = 0.5
MIN_OP_MOVE = 0.01
MIN_SAMPLES = 60
CHOICES = (("tight", "dead_time"), ("moderate", "tau"), ("robust", "3tau"))


def _pi(gain: float, tau: float, dead: float, lam: float) -> dict[str, float]:
    kc = tau / (abs(gain) * (lam + dead))
    ti = min(tau, 4.0 * (lam + dead))
    return {"lambda_seconds": round(lam, 1), "kc": round(kc, 4), "ti_seconds": round(ti, 1)}


def suggest(frame: pd.DataFrame, sample_seconds: float) -> dict[str, Any]:
    """The model fitted to ``frame`` (``pv`` and ``op`` on a regular grid) and PI settings for
    three closed-loop speeds; ``reason`` instead when there is no usable model."""

    if frame is None or frame.empty or not {"pv", "op"} <= set(frame.columns):
        return {"available": False, "reason": "The window has no PV and OP to fit a model to."}
    pv = pd.to_numeric(frame["pv"], errors="coerce").to_numpy(dtype=float)
    op = pd.to_numeric(frame["op"], errors="coerce").to_numpy(dtype=float)
    both = np.isfinite(pv) & np.isfinite(op)
    if both.sum() < MIN_SAMPLES:
        return {"available": False, "reason": "Too few samples with both PV and OP."}
    # The longest stretch with both signals: the fit needs consecutive steps.
    edges = np.diff(np.concatenate([[0], both.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    longest = int(np.argmax(ends - starts))
    part = slice(int(starts[longest]), int(ends[longest]))
    pv, op = pv[part], op[part]
    if len(pv) < MIN_SAMPLES:
        return {"available": False, "reason": "Too few consecutive samples with both PV and OP."}
    op_move = float(np.std(op)) / 100.0
    if op_move <= 0:
        return {"available": False, "reason": "The OP did not move in the window: nothing to fit."}
    max_dead = max(1, min(60, len(pv) // 10))
    try:
        fit = fit_fopdt(op, pv, float(sample_seconds), max_dead=max_dead)
    except ValueError as error:
        return {"available": False, "reason": str(error)}
    gain, tau, dead = fit.gain, fit.tau, fit.dead_seconds
    window = len(pv) * float(sample_seconds)
    if not (math.isfinite(gain) and math.isfinite(tau)) or gain == 0 or tau <= 0 or tau > window:
        return {
            "available": False,
            "reason": "The data gives no stable first-order model (an integrating process, or "
            "too little excitation).",
            "model": {"gain": gain, "tau_seconds": tau, "dead_time_seconds": dead, "r2": fit.r2},
        }
    reasons = []
    if fit.r2 < MIN_R2:
        reasons.append(f"the model explains {fit.r2:.0%} of the PV's variance (below {MIN_R2:.0%})")
    if op_move < MIN_OP_MOVE:
        reasons.append(f"the OP moved little (standard deviation {100 * op_move:.2f}% of range)")
    if tau < float(sample_seconds):
        reasons.append("the time constant is shorter than one sample: read faster data")
    if fit.dead_steps >= max_dead:
        reasons.append("the dead time is at the longest the search allows")
    lambdas = {"dead_time": max(dead, float(sample_seconds)), "tau": tau, "3tau": 3.0 * tau}
    return {
        "available": True,
        "reliable": not reasons,
        "caveats": reasons,
        "model": {
            "gain": round(gain, 6),
            "tau_seconds": round(tau, 1),
            "dead_time_seconds": round(dead, 1),
            "r2": round(fit.r2, 3),
            "samples": len(pv),
        },
        # A positive process gain needs a reverse-acting controller (more OP raises the PV).
        "action": "reverse" if gain > 0 else "direct",
        "settings": [
            {"choice": name, **_pi(gain, tau, dead, lambdas[key])} for name, key in CHOICES
        ],
    }
