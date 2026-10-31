# Stiction screening

## What it detects

The movement pattern of a sticky control valve: it stays stuck while the command moves inside
the stick band, then slips in one jump, and the loop cycles. The screen reads the share of the
output's moves that are stuck and the share of jumps right after a stuck move (stick then slip),
while the PV oscillates. It also reads the shape of a regular oscillation: a sticky valve makes
the controller output of a self-regulating loop (and the PV of a level) cycle in triangles, while
aggressive tuning or a disturbance from outside keeps the cycles round, like a sine.

## Reference

- Choudhury, Thornhill and Shah (2005), Modelling valve stiction, Control Engineering Practice
  13(5): the stick-band-then-slip model the screen looks for.
- Choudhury, Shah, Thornhill and Shook (2006), Automatic detection and quantification of stiction
  in control valves, Control Engineering Practice.
- He, Wang, Pottmann and Qin (2007), A curve fitting method for detecting valve stiction in
  oscillating control loops, Industrial & Engineering Chemistry Research 46(13): each half cycle
  fitted with a sine and with a triangle; index = sine error / (sine + triangle error).
- Jelali and Huang (2010), Detection and Diagnosis of Stiction in Control Loops (Springer):
  saturation is ruled out before a stiction test.
- Thornhill and Hägglund (1997): the PV oscillation test (autocorrelation peak).

## Parameters

- `movement_epsilon` (default 0.05): the largest output move, in %, that counts as stuck.
- `jump_threshold` (default 0.5): the smallest output move, in %, that counts as a jump (slip).
- `min_autocorrelation` (default 0.3): the PV autocorrelation peak at which the oscillation part
  of the score is full.
- `min_lag_samples` (default 3): the smallest lag, in grid samples, searched for the PV's
  autocorrelation peak.
- `jump_fraction_reference` (default 0.1): the share of stick-then-slip moves at which the slip
  part of the score is full.
- `lower_limit` (default 0): the output's lower limit; moves touching it are left out.
- `upper_limit` (default 100): the output's upper limit; moves touching it are left out.
- `margin` (default 1): how close to a limit a sample must be to be left out. An output outside
  `lower_limit`–`upper_limit` (a normalised record) is not checked for limits.
- `shape_index_high` (default 0.65): the curve-fitting index at which the shape part of the score
  is full (0.5 is undecided, 1 a pure triangle).
- `min_half_cycles` (default 4): the regular half cycles needed before the shape is judged; half
  cycles whose lengths spread more than 35% of their mean are no regular oscillation.

## How to read the finding

"Possible valve stiction: output stuck in 83% of the samples and jumping right after sticking in
14%, with the PV oscillating. This is a screening; confirm in the field." A diagnostic outside the
health score: confirm with a valve test (small output steps in manual), position feedback or a
full stiction method before planning maintenance. "Stiction not screened: the output sat at its
limit" means a saturated window, where stiction cannot be seen.

## Limits

- The stick-slip part needs an output that shows the valve's movement; the shape part needs a
  regular oscillation over a few cycles of the window. Horch's cross-correlation, the ellipse and
  bicoherence are not implemented (gap G28).
- Other causes (a quantised output, a slow positioner, deadband) can look similar.
