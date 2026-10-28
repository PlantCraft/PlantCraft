# Signal availability

## What it detects

Whether the loop's signals were recorded through the window: for each signal the coverage
(1 − the time lost in gaps longer than a maximum interval, over the window) and the largest gap.
Part of the data quality gate: if the PV covers too little of the window, the CPM methods do not
run.

## Reference

- Engineering heuristic. Historians with compression record only changes, so an interval up to
  the configured maximum still counts as valid data; data screening before any judgement is the
  first step the CPM survey (Bauer et al. 2016) describes.

## Parameters

- `max_gap_seconds` (default 600): the longest interval, in seconds, between two recorded samples
  that still counts as data; time beyond it is a gap. Slow loops (temperature, composition) get a
  longer interval from their loop type.
- `min_coverage` (default 0.8): the PV coverage below which the data are not usable and the CPM
  methods do not run.

## How to read the finding

"PV covers 97% of the window." When it says "PV covers only 40% of the window (minimum 80%)",
the loop's status is "Data not usable" and no performance score is given: fix the data path
(source connection, historian, signal mapping in PlantCraft) first.

## Limits

- It checks that values exist, not that they are right (see Value integrity).
- It does not tell a communication failure from stopped equipment.
