# PV variability

## What it detects

How much the process variable moves around its mean: standard deviation, range and coefficient
of variation over the window. Reducing variability is what lets a plant run closer to its limits.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Variance and
  standard deviation are basic CPM measures; the scoring is an engineering heuristic.

## Parameters

- `variability_tolerance` (default 1): the standard deviation, in the PV's unit, that scores 100
  (the worst); the score is the standard deviation divided by it.

## How to read the finding

"Standard deviation of 0.42 around the mean 50.1 (range 2.3)." Compare loops of the same kind, or
the same loop over time; on its own a number says little without the tolerance set for the
process.

## Limits

- Variability alone does not separate a controller problem from a process disturbance or from
  setpoint changes (the variability includes setpoint moves).
- The tolerance is absolute: set it per algorithm or loop for PVs not in % of span.
