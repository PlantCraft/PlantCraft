# Run history

**Results > Run history** lists every run of every algorithm on one list, newest first:
runs of the Signal quality algorithm over the signals, monitoring rounds and algorithm runs a person
or a monitor started on chosen loops. There is no separate page for signals and for loops: the
**Algorithm** and **Status** filters narrow the list, and each column sorts.

Each run shows when it started, the algorithm, what it ran on, its status, what it found, how long
it took and what started it. Open a run for its results and ask the assistant about it.

Runs are also reported to PlantCraft, which lists them on its Results page with the other
apps' runs.

## Monitors

**Monitors** says when each algorithm runs. A monitor's page has four parts:

- **What it runs**: the algorithm, the assets or loops it runs on and how much data each run reads.
- **When**: once, or every N minutes, hours, days, weeks or months. Every N minutes or hours can
  run only on some weekdays and only between two times of day (every 15 minutes, Monday to
  Friday, 06:00 to 18:00); days, weeks and months run at one or more times of day; months run on
  a day of the month (or its last day) or on a weekday such as the first Monday. A first and a
  last day are optional. Times follow the chosen time zone, the installation's local time or UTC
  first, so 06:00 stays 06:00 across daylight saving changes.
- **If it fails**: when a run cannot read the plant or finds no data, it tries again (twice, five
  minutes apart, by default) and gives up when the monitor's next occurrence comes first. An
  error in the algorithm itself is not tried again.
- **Owner and priority**: who answers for it (Alarms tells them), its place in the queue, how its
  runs spread out and whether it is active.

The preview on the right says the monitor in words and lists its next five occurrences. A saved
monitor shows its record above: how many runs ran, failed and were tried again, how long
they took and since when the last outcome holds.
