# A signal

One signal's data over the algorithm's window, with the events each check found drawn on the chart
(gaps, frozen stretches, spikes, values outside the limits), every check's result and the quality
history.

Editors can:

- **Check now**: judge the signal again over the algorithm's window (saved), or over another
  window (not saved).
- **Change its settings**: limits that override PlantCraft's, a reference signal for the drift
  check, checks switched off or on for this signal, and parameters for its checks.
- **Switch it off**: the algorithm skips it.

Signals with the setpoint, mode or controller output role in a PlantCraft asset skip the frozen
value check: a setpoint and a mode are constant by design, and an output held still is the loop's
state (a saturated valve, manual mode), which the loop methods judge. Switch it on for one signal
if you want it.

## Laboratory analyses

A signal from a file source (CSV: laboratory analyses, manual entries) is **sampled** and is not
judged as a process signal. Its value repeats until the next analysis and samples hours apart are
normal, so it skips the frozen value, noise and resolution checks. Freshness and gaps are
measured against its sampling interval: a warning once an analysis is late by half an interval,
bad at three intervals without one. Range, spikes (jumps between samples) and drift still judge
it. The interval is read from the samples themselves (4 h when there are too few); set it in
**Sampling interval**. **Sampling** marks any signal as laboratory or as continuous, whatever
its source.
