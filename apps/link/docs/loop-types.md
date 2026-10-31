# Analysis defaults per loop type

> **Updated:** 2026-10-23 · code: `src/linkcraft/catalog/loop_types.py`, algorithms in
> `src/linkcraft/blocks/algorithms.py` ([blocks and algorithms](blocks-and-algorithms.md))

PlantCraft's asset record says what each control loop controls (attribute `loop_type`) and how
much it matters (`criticality`). PlantCraft Analytics starts every loop from those two values; a person can
change the result on the loop page, and that choice is kept in PlantCraft Analytics' own database and wins
over the record from then on (the page says "from the asset record" or "set here" next to each
setting, and "Use the asset record" gives a setting back).

## The table

Each loop type starts with the algorithm made for it (round 6, 2026-10-23): **Flow loop**
(`flow_loop`) for flows and loops of unknown type, **Level loop** (`level_loop`) for levels and
**Temperature or pressure loop** (`temperature_loop`) for the slow loops with dead time
(temperature, pressure, composition); **Surge level** (`surge_level`) is chosen on the loop page
for a level that averages its inflow. Flow loop scores the PV–SP error, output saturation, valve
travel and sampling quality and flags stiction, oscillation and noise; Level loop does the same
for a level held tight; Temperature or pressure loop adds the minimum-variance (Harris) index;
manual mode, setpoint activity and operator interventions are context in all. What differs
between types is also how fast the process is, so the loop type sets method parameters under the
algorithm's. The old ids still name their replacement: the 0.2 protocols (`flow_control` as
`flow_loop`, `level_control` as `level_loop`, `temperature_control`, `pressure_control` and
`composition_control` as `temperature_loop`, `surge_drum` as `surge_level`) and the 0.3
algorithms Loop health, Control valve and Oscillation and noise (`loop_health`, `control_valve`,
`oscillation_noise`), all three as `flow_loop`.

| `loop_type` | Starting algorithm | Method parameters from the loop type | Why |
|---|---|---|---|
| `flow` | Flow loop (`flow_loop`) | `op_travel_reversal`: travel up to 400 %/h, 120 reversals/h; `sensor_noise_ratio`: `noise_ratio_threshold` 0.25; `stiction_screening`: `movement_epsilon` 0.03 % | Fastest loops (time constants of seconds), turbulent and noisy measurement, a valve that moves all the time by design: twice the general travel and reversal allowance before calling it wear, noise screened more strictly and stiction on smaller moves. |
| `level` | Level loop (`level_loop`) | `op_travel_reversal`: 100 %/h, 30 reversals/h | The record says a level is controlled, not whether it is held tight or averaged inside a band, so a level starts as tight and is scored on the PV–SP error (relative to its setpoint, like every type). For an averaging (surge) level, whose job is to absorb flow upsets inside its band and pass a smooth flow on, pick **Surge level** (`surge_level`: disturbance attenuation, time in band 20–80, interventions, saturation, manual mode, valve travel, sampling) on the loop page. Until 2026-10-19 that was the default; it scored the demo's tight levels 52–56 and could not tell their faults apart (G34). |
| `pressure` | Temperature or pressure loop (`temperature_loop`) | none (method defaults: 200 %/h, 60 reversals/h) | Fast to medium (seconds to a minute) and must hold its setpoint; the method defaults were written for such loops. Oscillation and stiction are the common faults, both flagged as diagnostics. |
| `temperature` | Temperature or pressure loop (`temperature_loop`) | `op_travel_reversal`: 100 %/h, 30 reversals/h; `setpoint_activity`: 2 changes/h; `dq_availability`: gaps up to 900 s | Slow (minutes; thermowell and heat-transfer lags), smooth measurement: setpoints move rarely and a valve that hunts is a problem sooner. Historians compress slow temperatures heavily, so longer gaps between recorded samples are still valid data. |
| `composition` | Temperature or pressure loop (`temperature_loop`) | `op_travel_reversal`: 2000 %/h, 600 reversals/h; `setpoint_activity`: 1 change/h; `dq_availability`: gaps up to 1800 s | Slowest (minutes to hours), often an analyser updated every few minutes and the primary of a cascade whose output is a flow setpoint, not a valve: its output moves are its job, not valve wear (0.2's composition protocol left valve travel out), few setpoint moves, and long gaps between analyser updates are normal. |
| missing or unknown | Flow loop (`flow_loop`) | none | The record does not say what the loop controls: Flow loop runs with the method defaults. |

`criticality` (`low`, `medium`, `high`) becomes the loop's criticality in PlantCraft Analytics, which weights
its ranking: points lost from 100 times 0.6 (low), 1.0 (medium), 1.5 (high) or 2.0 (critical,
only set here). A missing or unknown value is `medium`. `action` (`direct`, `reverse`) and
`controller` (`DCS`, `SLC`) are shown on the loop page; no method uses them yet.

## Order in which parameters apply

1. the method's own default (or the default an admin saved on the method's page);
2. the loop type's parameters (table above);
3. the algorithm's parameters (what its diagram sets on each block);
4. parameters a person set on the loop in PlantCraft Analytics;
5. a run's own overrides.

So an algorithm chosen on the loop page keeps the loop type's time-scale parameters unless the
algorithm sets them itself.

## Incomplete records

A loop asset without a signal for a role its type requires (`pv` and `op` for a control loop;
PlantCraft Analytics reads them from `GET /api/v1/asset-types`, and assumes `pv` and `op` when PlantCraft
does not serve it) is listed with the status "Incomplete record" and the roles missing. It is not
analysed and runs on it are refused, until the roles are bound on the asset's page in
PlantCraft; the next sync picks them up.

## Limits

- Parameters counted in samples (`min_lag_samples` of the oscillation and stiction screens) and
  rates per hour see the analysis grid (`LINKCRAFT_RESAMPLE_SECONDS`, 60 s by default), not the
  historian's own sampling: on a 60 s grid an oscillation faster than about 3 minutes, common in
  flow loops, cannot be seen, and at most 60 reversals per hour can be counted (so the flow
  loop's 120 per hour bites only on a finer grid).
- `sampling_quality` judges the recorded samples, not the grid (G31 fixed 2026-10-19), but the
  loop types set no recommended interval for it yet: it runs with the method's defaults.
