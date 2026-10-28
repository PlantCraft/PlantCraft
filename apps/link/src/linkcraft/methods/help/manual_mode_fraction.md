# Manual mode

## What it detects

The share of the window in which the controller was not in automatic, from the mode signal
(texts such as `MAN` or numeric modes).

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Time in manual is
  the first industrial CPM indicator: a loop in manual delivers none of its benefit.

## Parameters

- `manual_labels` (default manual, man, m): the mode texts (any case) that mean manual operation;
  add your system's labels (for example `cas` is automatic, `lo` may be manual).
- `warning_fraction` (default 0.1): the share of the window in manual at which the score reaches
  100; the score is the manual share divided by it.

## How to read the finding

"The loop was out of automatic 35% of the time." This is context, shown beside the health score:
operator behaviour, not controller performance. A loop in manual for half the window or more is
marked inactive and gets no health score. Frequent manual operation usually means the operators
do not trust the loop: look at tuning, the valve and the measurement.

## Limits

- Manual operation may be intended (maintenance, start-up, abnormal conditions).
- Needs a mode signal with reliable labels; numeric modes count as manual only when their value
  is listed (`0` is read as manual by the operating-state check).
