# Estimators in Models: virtual sensors and Kalman filters (design, prototype)

Status: prototype of 2026-10-31 (item E3.2 of the Saturday test plan). The math is in the SDK,
`plantcraft_sdk.estimators` (NumPy only, tests in `sdk/python/tests/test_estimators.py`), so
Models and Analytics share one copy. Analytics runs it as blocks (library "Estimators":
`estimator.kalman`, `estimator.drift`, `estimator.soft_sensor`, `estimator.lab_fusion`) and
ships them wired as the
"Virtual sensor" algorithm (a loop's valve and measurement: filtered value, uncertainty, sensor
bias, graded by the mean bias). The Models object below (estimator, fit as a study) is the next
step.

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
| **Lab fusion** (Kalman, delayed measurement; `fuse_lab`, block `estimator.lab_fusion`) | "what is the quality now, with the lab's accuracy and the analyzer's speed?" | the online value (analyzer or soft sensor) and the lab results at their sampling times, known when approved | corrected value, bias, uncertainty; `sensor_health` grades a virtual sensor 0 to 100 against the lab |
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

The FOPDT fit is a one-step least squares refined on the simulated response (output error):
on smooth data the one-step fit alone calls the process an integrator.

| Case | Raw sensor RMSE | Best classic | Kalman | Gain |
|---|---|---|---|---|
| AIC-307 noisy analyzer | 0.0294 | 5 min moving average 0.0038, 135 s late | model-based 0.0008, no lag | 39x |
| AIC-504 noisy analyzer | 0.0289 | 5 min moving average 0.0033, 220 s late | model-based 0.0007, 75 s | 41x |
| Second order process fitted as FOPDT | 0.0289 | 5 min moving average 0.0033, 190 s late | model-based 0.0007, 35 s | 41x |
| TIC-203 drifting sensor | 0.0560 | (none sees a drift) | bias state, corrected 0.0057; bias tracked to 0.0056 | 10x |
| AIC-307 with a lab every 30 min | held lab value 0.0253 | soft sensor 0.0045 | model + lab 0.0030 | 8x |

### With the model wrong on purpose

| Error in the model | Effect on the Kalman error |
|---|---|
| Dead time ×0, ×0.5 or ×2 | none to +15% |
| A second order process fitted as a first order | none (the row above) |
| Time constant ×0.5 | up to +70% |
| Time constant ×2 | 2x to 3.5x, and 375 to 475 s late |
| Gain ×0.7 or ×1.3 | 3x to 7x; retuning the noise recovers about half |

So the gain is what to refit from time to time (a fit is cheap: tuning and filtering 17,280
samples takes 0.19 s). The Simulator's loops are FOPDT, the very structure the filter assumes,
so the right-model rows are an upper bound; the next check is on recorded plant data.

## Lab fusion: results that arrive late

A lab result says what the quality was when the sample was taken, and it is known hours later,
once approved (the Historian keeps both times, `lab_samples`). `fuse_lab` treats the online
value's bias as a random walk; a result sampled at step s and approved at step a measures the
bias of step s, so at step a it counts as a measurement of the bias now with the walk of the
a − s steps added to its noise (Alexander, 1991). Nothing moves before a result is approved,
and a result never approved never corrects: replayed on history, the estimate is what an
operator would have seen. The walk is tuned by maximum likelihood of the results'
innovations. In the tests, a drift of 3 units over 4 hours with a result every 5 minutes
approved 100 s late is cut more than 4 times (`sdk/python/tests/test_lab_fusion.py`).
