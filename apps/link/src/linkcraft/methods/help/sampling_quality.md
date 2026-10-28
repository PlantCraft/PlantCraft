# Sampling quality

## What it detects

Whether the source records the loop finely and regularly enough to judge it: the median interval
between the PV's recorded samples (as PlantCraft returns them, before the analysis grid), its
95th percentile, the number of gaps (intervals much longer than the median) and the largest one.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Too coarse or
  compressed historian data is one of the main practical obstacles the survey reports.
- Thornhill, Choudhury and Shah (2004), The impact of compression on data-driven process
  analyses, Journal of Process Control. The score is an engineering heuristic.

## Parameters

- `recommended_sample_seconds` (default 30): the interval, in seconds, a loop of this kind should
  be sampled at; each multiple above it costs 60 points of score.
- `gap_multiplier` (default 2.5): an interval longer than this multiple of the median counts as a
  gap; gaps cost up to 40 points.

## How to read the finding

"The PV was recorded every 10 s (median; recommended up to 30 s), with 0 gaps." The performance (100 minus the
score) multiplies into the loop's health.

## Limits

- Historian compression (record on change) lengthens the intervals of a steady signal; the method
  takes them as they are, since such data really are coarser for the other methods.
- When a window holds too many recorded values for one read (more than 200,000 points),
  PlantCraft returns one mean per grid step and the method sees that step. A caller that gives
  no recorded samples gets the grid's timestamps; the result says which it judged
  (`timestamp_source`).
