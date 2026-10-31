# PV–SP error

## What it detects

How far the process variable stays from its setpoint over the window: the mean absolute error
(MAE), RMSE, the integral of the absolute error (IAE), of the squared error (ISE) and of the
time-weighted absolute error (ITAE), and the share of the time the PV stays inside an acceptable
band around the setpoint. It is the basic tracking measure of a loop that must hold or follow its
setpoint.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Error integrals
  are the most used performance measures in the industrial tools the survey covers, which rank a
  plant's whole loop population by such KPIs. An error in the PV's own unit cannot be ranked
  across loops (a mean error of 1 is nothing for a flow of 500 t/h and a lot for 2 bar), so the
  error is scored against a share of each loop's scale. The 4 % default is an engineering
  heuristic, not a benchmark from a paper.

## Parameters

- `error_tolerance` (default none): an absolute mean absolute error, in the PV's unit, that
  scores 100 (the worst). Empty: the tolerance is `relative_tolerance_percent` of the loop's
  scale. An algorithm or loop that sets it uses it as given.
- `acceptable_band` (default none): an absolute half-width, in the PV's unit, of the band around
  the setpoint that counts as on target. Empty: `relative_band_percent` of the scale.
- `relative_tolerance_percent` (default 4): the mean absolute error that scores 100, in percent
  of the loop's scale; an error of 1 % of the scale costs 25 points.
- `relative_band_percent` (default 1): the on-target band, in percent of the loop's scale.
- `pv_span` (default none): the PV's engineering span. When given it is the loop's scale; empty,
  the scale is the size of the setpoint (median |SP|) over the window.

## How to read the finding

"PV–SP mean absolute error of 0.8; the PV was within ±0.5 of the setpoint 64% of the time."
The result also gives the tolerance it used, the scale and its basis (`pv_span`, `setpoint`, or
`absolute` when a tolerance was given or the setpoint sits at zero).
The performance shown is 100 minus the score, so 100% means no error and 0% an error at or above
the tolerance; it multiplies into the loop's health. A large error with a pinned output points
to saturation (see Output saturation); with a cycling PV to oscillation; with frequent setpoint
moves to setpoint activity rather than poor tuning.

## Limits

- PV and SP must be in the same engineering unit.
- A high error can come from constraints, disturbances or a setpoint the process cannot reach,
  not only from tuning.
- Without a span, the setpoint's size is the scale: right for PVs far from zero (flows, levels,
  temperatures in °C), too tight for one held near zero (a gauge pressure, a differential).
  Give such loops their `pv_span` or an absolute `error_tolerance`. PlantCraft does not keep
  signal ranges yet; when it does, the span can come from there (gap G36).
- The error is not compared here with what the best possible controller would achieve: that is
  the minimum-variance (Harris) index, `harris_index`.
