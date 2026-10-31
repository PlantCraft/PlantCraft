# Estimators in Models: virtual sensors and Kalman filters (design, prototype)

Status: prototype of 2026-10-31 (item E3.2 of the Saturday test plan). The math is in the SDK,
`plantcraft_sdk.estimators` (NumPy only, tests in `sdk/python/tests/test_estimators.py`), so
Models and Analytics share one copy. Analytics runs it as blocks (library "Estimators":
`estimator.kalman`, `estimator.drift`, `estimator.lab_fusion`); the Models object below
(estimator, fit as a study) is the next step.

## What a person gets

An **estimator** is a Models object, beside models and studies, that turns signals the plant
already measures into a better estimate of one it measures badly or not at all, and writes that
estimate back to the Historian as a derived signal (`app-modelcraft:<estimator>.<output>`), so it
shows in View, Analytics and Alarms like any other signal.

| Kind | Answers | Inputs | Output |
|---|---|---|---|
| **Noise filter** (Kalman, no model) | "what is the value behind this noisy transmitter?" | the signal | filtered value, its uncertainty |
| **Model-based filter** (Kalman with a first order plus dead time, FOPDT) | same, without the lag a moving average adds; bridges gaps | the signal and what drives it (a valve, a feed) | filtered value, uncertainty, innovation |
| **Drift watch** (Kalman with a bias state) | "is this sensor drifting, and by how much?" | the signal and what drives it | corrected value, estimated bias (alarmable) |
| **Lab fusion** (Kalman, sparse measurements) | "what is the quality between lab samples?" | the lab or analyzer value, when it exists, and the drivers | value every step, uncertainty that grows between samples |
| **Soft sensor** (ridge regression on lagged inputs) | "estimate X from Y and Z" when no physical model is at hand | several signals and the target's samples | estimate, validation error |

Later, in the same frame: extended/unscented Kalman with a Modelica model (the model's FMU as
the process), moving-horizon estimation, data reconciliation (mass and energy balances), PLS
and neural soft sensors. These are what the vendors sell under "soft sensors", "inferentials"
and "state estimation" (AspenTech IQ/Aspen Inferential Qualities, AVEVA/OSIsoft soft sensors in
Advanced Analytics, Honeywell Profit Suite inferentials, Yokogawa and Emerson soft sensors, Seeq's
regression and Kalman add-ons); the vendor survey is item E3.1 of the plan.

## How it fits Models

- **Object**: `estimator` in a project, with its kind, inputs (`signal:<source>:<tag>`),
  sample time, the fitted model (gain, time constant, dead time, offsets, noise variances) and
  a version per fit. Shared and permissioned like models.
- **Fit**: a run on the queue, over a window of history the person picks (the "fit window");
  it shows the FOPDT fit (R², step response), the noise estimate and the tuned process noise,
  and a hold-out check (error on the last part of the window). A fit is a study type, like the
  optimization study.
- **Run**: a schedule, every N minutes, reads only the new samples (and the filter's last state,
  kept in SQLite), steps the filter and writes the outputs as derived signals in one batch. The
  filter's state makes it incremental: no re-read of the day.
- **Blocks**: the same functions as blocks in the block editor (Analytics, Alarms) through the SDK,
  so an alarm rule can use "bias of TT-203 above 2%".
- **Assistant**: "Explain this estimator" and "Suggest the inputs" works, reading the fit report.

## Measured on the Simulator's hidden truth (24 h, 5 s steps; fit on the first half)

| Case | Raw sensor RMSE | Best classic | Kalman | Gain |
|---|---|---|---|---|
| AIC-307 noisy analyzer | 0.0294 | 5 min moving average 0.0038, 135 s late | model-based 0.0027, no lag | 11x |
| AIC-504 noisy analyzer | 0.0289 | 5 min moving average 0.0033, 220 s late | model-based 0.0016, no lag | 18x |
| TIC-203 drifting sensor | 0.0560 | (none sees a drift) | bias state, corrected 0.0057; bias tracked to 0.0056 | 10x |
| AIC-307 with a lab every 30 min | held lab value 0.0253 | soft sensor 0.0045 | model + lab 0.0030 | 8x |

Caveat: the Simulator's loops are FOPDT, the very structure the filter assumes, so these are an
upper bound. The next check is on recorded plant data (the demo's Historian) and with a
mismatched model (wrong dead time, a second order process).
