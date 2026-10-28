# Valve travel

## What it detects

How hard the valve works: the accumulated output movement per hour (travel) and the number of
direction changes per hour (reversals). Excess travel and reversals wear packing and actuators
and often come from noise or aggressive tuning.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Valve travel and
  reversals are standard valve-health indicators; the thresholds are engineering heuristics.

## Parameters

- `max_travel_per_hour` (default 200): the accumulated output travel, in % per hour, that scores
  100. Fast loops (flow) are allowed more and slow or averaging ones less by their loop type.
- `max_reversals_per_hour` (default 60): the number of direction changes per hour that scores
  100.
- `reversal_epsilon` (default 0.05): the smallest output move, in %, counted when looking for a
  direction change.

## How to read the finding

"The output travelled 320% per hour, with 45 reversals per hour." The score is the worse of the
two rates. High travel with a noisy PV points to noise reaching the valve (filter, derivative);
high travel with an oscillation to tuning or stiction.

## Limits

- The output is the controller's command, not the stem position.
- Counted on the analysis grid: the averaging over each grid step hides fast movement, and at
  most one reversal per grid sample can be counted.
