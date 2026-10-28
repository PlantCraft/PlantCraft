# Disturbance attenuation

## What it detects

Whether an averaging (surge) level loop does its job: absorb inflow disturbances in the vessel
and pass a smooth outflow on. It compares how much the controller output travels with how much
the level travels, both normalised to their ranges. An output that moves more than the level
passes the disturbances on downstream instead of using the vessel's capacity.

It applies only to surge levels: loops whose asset record says `level`, or loops on the surge-level
algorithm, which sets `assume_surge_level`. On a flow, pressure, temperature or composition loop,
or on a loop whose record gives no loop type, it returns "not applicable" with the reason and
stays out of the loop's health (it does not count as a zero).

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Averaging level
  control is judged by the outflow it passes on, not by tracking.
- Shinskey (1996), Process Control Systems: Application, Design and Tuning, McGraw-Hill.
  Textbook treatment of averaging level control: the vessel absorbs disturbances so the outflow
  stays smooth. The amplification ratio and its thresholds are an engineering heuristic built
  on that idea; tune them per plant.

## Parameters

- `pv_range` (default 100): the PV's span used to normalise its travel (100 for a level in %).
- `op_range` (default 100): the output's span used to normalise its travel (100 for an output in %).
- `full_performance_factor` (default 0.5): the amplification (normalised OP travel over normalised
  PV travel) that scores 100%: the outflow moves half as much as the level.
- `zero_performance_factor` (default 1.5): the amplification that scores 0%; in between the
  performance falls linearly.
- `movement_epsilon` (default 0.01): the smallest normalised PV travel needed for a stable ratio;
  below it the method reports not enough data (a level that did not move).
- `assume_surge_level` (default false): run on a loop whose asset record gives no loop type; the
  Surge level algorithm sets it, because choosing that algorithm says the loop is a surge level.

## How to read the finding

"The output moves 1.8 times the normalized PV movement: the control passes disturbances on
instead of absorbing them in the level." A factor below 1 is what an averaging level should do;
above 1 the level is held too tightly (tuning too aggressive for averaging) and the downstream
units see the upsets.

## Limits

- Only for averaging level control; on a tight level loop a high factor is intended. A level
  whose record says `level` but which is held tightly needs another algorithm.
- Wrong PV or OP ranges make the ratio meaningless.
- A level that barely moves gives no stable ratio.
