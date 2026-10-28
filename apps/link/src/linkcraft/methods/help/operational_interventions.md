# Operator interventions

## What it detects

How often people (or a supervisory layer) intervene on the loop: setpoint changes plus switches
of the controller mode, scaled to a reference window. A loop that needs constant attention is
not doing its job, even when its error looks small.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Counting operator
  interventions is a common industrial measure.
- Jelali (2006), An overview of control performance assessment technology and industrial
  applications, Control Engineering Practice. Lists operator interventions among the practical
  KPIs of industrial CPA. The thresholds are an engineering heuristic; tune them per plant.

## Parameters

- `sp_change_threshold` (default 0.1): the smallest setpoint move, in the PV's unit, counted as an
  intervention; smaller moves are noise or rounding.
- `reference_hours` (default 12): the window, in hours, the count is scaled to (one shift).
- `full_performance_max` (default 2): up to this many interventions per reference window the
  criterion scores 100%.
- `zero_performance_min` (default 12): from this many interventions per reference window on the
  criterion scores 0%; in between it falls linearly.

## How to read the finding

"3 setpoint changes and 1 mode switch in the window, equivalent to 2 interventions every 12 h."
This is context: it is shown beside the health score and never multiplied into it, because a busy
operator must not make a good controller look bad. Many interventions on a loop with a good score
suggest the operators do not trust it, or that the setpoint is driven by a recipe or APC.

## Limits

- Recipes, APC, start-ups and grade changes move setpoints on purpose.
- Needs SP or mode; without either it reports not enough data.
- A supervisory layer writing the setpoint at every sample (a cascade secondary) counts every
  write; do not use it on cascade secondaries.
