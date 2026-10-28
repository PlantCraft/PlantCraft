# Oscillation

## What it detects

A sustained, regular oscillation of the loop: of the control error (PV − SP) when the setpoint is
known, else of the PV. Oscillation is the most common performance problem of industrial loops,
caused by aggressive tuning, a sticky valve or an oscillating disturbance from another loop.

## Reference

- Thornhill and Hägglund (1997), Detection and diagnosis of oscillation in control loops,
  Control Engineering Practice: the oscillation shows as a clear peak of the autocorrelation
  function (ACF) after lag zero.
- Thornhill, Huang and Zhang (2003), Detection of multiple oscillations in control loops, Journal
  of Process Control 13(1): the regularity r = mean period / (3 × standard deviation of the
  periods between alternate ACF zero crossings); the oscillation is regular when r > 1.

## Parameters

- `min_lag_samples` (default 3): the smallest ACF lag, in samples of the analysis grid, searched
  for the peak; it sets the shortest period that can be seen.
- `max_lag_samples` (default none): the largest lag searched; none uses the whole window.
- `min_cycles` (default 3): the number of cycles the window must hold before the score is full; a
  period too long for the window lowers the score.
- `min_autocorrelation` (default 0.3): the ACF peak from which a repeat counts as oscillation.
- `min_regularity` (default 1): the regularity r from which the oscillation counts as sustained
  (Thornhill, Huang and Zhang use 1).

## How to read the finding

"Oscillation with a period of about 5 min, 72 cycles in the window (autocorrelation 0.89,
regularity 100)." It is a diagnostic shown as an alert, not part of the health product. The
period helps find the cause: a period close to the loop's own response time points to tuning or
the valve; the same period in several loops points to one source spreading through the plant
(see Loop interaction). "No sustained oscillation ... period is irregular" means a one-off upset
or setpoint step, not a cycle.

## Limits

- A screening: it does not tell an oscillation caused by tuning from one caused by an external
  disturbance (gap G29) or by stiction (see Stiction screening).
- Periods shorter than about three grid samples (3 min on the default 60 s grid) cannot be seen.
- An oscillation whose period drifts strongly in the window is not regular and is not flagged.
