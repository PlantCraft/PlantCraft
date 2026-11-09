# Sensor noise

## What it detects

Noise on the measurement, judged against the loop's own scale: the sample-to-sample noise
estimated from the PV's second differences (with the median absolute deviation, so setpoint steps
and load changes do not count), as a share of the PV span or, without one, of the setpoint's size.
Noise passes through the controller to the valve and wears it, and it hides what the loop does.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. The measure is an
  engineering heuristic.

## Parameters

- `relative_noise_percent` (default 2): the noise, in percent of the loop's scale, that scores
  100 (the worst); warning from a quarter of it.
- `noise_ratio_threshold` (default 0.35): the share of the PV's variation explained by noise at
  which the noise weighs fully. A PV that cycles or moves a lot has most of its variation outside
  the noise, and its sample-to-sample moves are its cycle more than noise: the score is lowered.
- `noise_abs_tolerance` (default none): an absolute noise, in the PV's unit, that scores 100.
  Empty: a share of the loop's scale.
- `pv_span` (default none): the PV's engineering span; empty, the scale is the median |SP| (or
  |PV| without a setpoint).

## How to read the finding

"Sample-to-sample noise of 1.3 (2.6 % of the loop's scale), 95% of the measurement's variation."
A diagnostic shown as an alert, outside the score. Noise above about 0.5 % of the scale on a
tight loop is worth a look at the transmitter, its impulse lines, its filtering and the
derivative action; analysers are naturally noisier than temperatures.

## Limits

- A process faster than the sampling (a fast flow sampled once a minute) looks like noise.
- On a coarse grid the averaging hides noise.
- A PV held near zero makes the relative tolerance tight: give the loop its `pv_span` or an
  absolute `noise_abs_tolerance`.
