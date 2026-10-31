# Overview

The first page of Analytics: a board of widgets that only shows, with no buttons on top. A run
starts on Monitors (each monitor's **Run now**), never here.

A new person's board answers one question, which assets and signals are bad now, and where:

- **Results by status**: every result split into alarm, warning, unknown and OK. Each part opens
  the matching results.
- **In alarm, 14 days**: how many were in alarm and in warning at the end of each day.
- **Health map**: one square per asset and signal, coloured by its status and grouped by area.
  Each square opens its result.
- **Worst results**: those in alarm or warning, the lowest health, quality or score first.
- **Monitors**: each monitor, when it runs and how its last run ended.
- **Queue**: what waits and runs now, and the queue over the last 24 hours.
- **Loop-hours lost, 7 days**: by area, the time each loop was not controlling, split by cause:
  out of normal mode, output at a limit, oscillating and bad signal.
- **Effective control**: the loops with the lowest score first. The score is the share of the
  time in normal mode, times inside the operating band, times with the output off its limits.
- **Oscillations shared by several loops**: loops that cycle with periods within 15% of each
  other, grouped. The loop to look at first in each group is the one with stiction, then the one
  with the most regular cycle.
- **Plant map**: every loop coloured by the KPI you pick (health, effective control, time in
  normal mode, time inside the band, time with the output off its limits). Good is from 90, fair
  from 75, poor from 50, bad below. **Heat map** groups the loops by area; the treemap sizes them
  by criticality, so the critical loops take the most room. Each loop opens its page.

More widgets wait in **Customize**: **Analytics: closest to the limit** lists the loops whose health is
falling and how many days are left until it reaches the alarm limit (50). The forecast is a line
fitted to the last 14 days, shown only when it fits (R² of at least 0.5) and the limit is less
than a year away. **Analytics: multivariable controllers** shows each third-party APC with its costliest
active limit.

**Customize** adds, moves and removes widgets for you alone: one monitor, one result, the last
run and the others Analytics publishes. The same widgets can go on Desk's Today.
