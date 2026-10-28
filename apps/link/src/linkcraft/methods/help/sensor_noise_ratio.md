# Sensor noise

## What it detects

High-frequency noise on the measurement: the spread of the sample-to-sample changes (divided by
√2, the noise level of white noise) compared with the PV's total spread, and in absolute terms.
Noise passes through the controller to the valve and wears it.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. The measure is an
  engineering heuristic.

## Parameters

- `noise_ratio_threshold` (default 0.35): the share of the PV's variation attributed to noise at
  which the ratio part of the score is full (it weighs 35%).
- `noise_abs_tolerance` (default 0.5): the noise amplitude, in the PV's unit, at which the
  absolute part of the score reaches 100.

## How to read the finding

"High-frequency noise is 42% of the measurement's total variation." A diagnostic shown as an
alert. High noise suggests checking the transmitter, its filtering and the derivative action;
flow measurements are naturally noisier than temperatures.

## Limits

- Real fast process dynamics look like noise without the process context.
- On a coarse grid the averaging hides noise; the absolute tolerance is in the PV's unit.
