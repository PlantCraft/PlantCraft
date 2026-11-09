# Output drift

## What it detects

The controller output walking steadily one way, hour after hour, while the PV holds its
setpoint. A transmitter that drifts makes the controller hold the wrong reading: the PV looks
perfect while the process moves away, and the only trace in the loop's data is the output
following the drift. Fouling, a wearing valve or a feed that changes slowly leave the same trace.

The window is cut into blocks (an hour by default); the drift is the median change of the
output's median from one block to the next, counted only between blocks where the setpoint held,
so one step (a calibration, a setpoint move) does not count. It is scored when most changes go
the same way.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. The measure is an
  engineering heuristic.

## Parameters

- `block_minutes` (default 60): the length of the blocks whose median output is compared.
- `drift_per_day` (default 6): the drift, in % of OP per day, that scores 100.
- `min_consistency` (default 0.6): the share of block-to-block changes in the drift's direction
  from which the drift counts.
- `full_consistency` (default 0.8): the share at which the drift counts fully.
- `min_blocks` (default 8): the fewest blocks with a steady setpoint needed to judge.

## How to read the finding

"The output drifts down by about 7 % per day (91% of the block-to-block changes the same way)
while the setpoint holds: a drifting transmitter, fouling or a slow load change." A diagnostic
shown as an alert, outside the score. Compare the PV with a redundant measurement, a lab result
or a balance: a drifting transmitter needs calibration. If it reads right, look for fouling,
valve wear or a feed that changes slowly.

## Limits

- It cannot tell a drifting transmitter from a slow process change: confirm in the field.
- A drift calibrated back inside the window, or slower than the window, reads weaker.
- A loop whose setpoint moves every hour has too few steady blocks to judge (no result).
