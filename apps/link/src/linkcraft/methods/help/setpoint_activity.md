# SP activity

## What it detects

How often the setpoint moved by more than a threshold, as changes per hour, and the total
movement. Frequent setpoint moves by operators often hide a loop that does not hold its target on
its own.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. The scoring is an
  engineering heuristic.

## Parameters

- `change_threshold` (default 0.1): the smallest setpoint move, in the PV's unit, counted as a
  change.
- `max_changes_per_hour` (default 6): the rate of changes per hour that scores 100; the score is
  the rate divided by it. Slow loops (temperature, composition) get a lower rate from their loop
  type.

## How to read the finding

"14 setpoint changes (0.6 per hour)." A high rate on a loop whose setpoint is set by people says
they keep correcting it; on a cascade secondary or an APC-driven loop it is expected.

## Limits

- Recipes, transitions and APC move setpoints on purpose.
- A cascade secondary's setpoint is written by its primary at every sample: every sample counts
  as a change.
