# Minimum-variance index

## What it detects

How far the loop's variance is above the smallest variance any controller could reach with the
loop's dead time: the minimum-variance (Harris) index. It is the classic benchmark of control
loop performance assessment and needs only routine operating data, no step test.

## Reference

- Harris (1989), Assessment of control loop performance, The Canadian Journal of Chemical
  Engineering 67(5): the part of the error that falls inside the dead time cannot be removed by
  feedback, so its variance is the minimum-variance benchmark; the index is that benchmark over
  the actual variance.
- Horch and Isaksson (1999), A modified index for control performance assessment, Journal of
  Process Control 9(6): why the minimum-variance bound is often out of reach in practice and an
  index well below 1 can still be a good loop.
- Bauer et al. (2016), The current state of control loop performance monitoring, Journal of
  Process Control: the index's use and its pitfalls in industry.

## Parameters

- `dead_time_seconds` (default 0): the loop's dead time; 0 estimates it as the lag, in samples,
  of the largest cross-correlation between OP moves and PV moves (one sample when there is no OP).
- `ar_order` (default 20): the order of the autoregressive model fitted to the control error;
  it is raised to the dead time plus one when the dead time is longer.
- `max_delay_samples` (default 60): the longest dead time, in samples, looked for when it is
  estimated from OP and PV.
- `good_index` (default 0.5): the index at or above which the loop scores healthy; well-tuned
  industrial loops usually sit between 0.3 and 0.6.
- `poor_index` (default 0.1): the index at or below which the score is 100; the score falls
  linearly between the two.

## How to read the finding

"The variance is 4.2 times the minimum-variance benchmark (dead time 7 samples): retuning could
remove up to 76% of it." An index near 1 means the loop already rejects disturbances about as
well as feedback can; a low index points to sluggish or oscillating control, where retuning, a
valve repair or feedforward can pay. Check the dead time it used (`delay_source`: parameter,
estimated or assumed): an estimated or assumed one should be confirmed before acting.

## Limits

- Minimum variance is a theoretical bound that usually needs aggressive control and large OP
  moves; the index says how much could be gained, not that it should be.
- A wrong dead time moves the index: a shorter one makes the loop look worse.
- Setpoint changes, saturation and manual mode in the window distort it; it is not part of the
  shipped algorithms and is added to an algorithm when wanted.
