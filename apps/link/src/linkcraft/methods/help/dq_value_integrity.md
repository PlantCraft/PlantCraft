# Value integrity

## What it detects

Whether the PV's values can be trusted: the share of invalid samples (text, infinity, empty,
outside the physical limits when set) and the longest stretch over which the PV stayed exactly
constant (a frozen transmitter). Part of the data quality gate.

## Reference

- Engineering heuristic: a real process value never stays exactly constant for long; a frozen or
  invalid measurement is ruled out before judging the loop, as in every CPM tool the survey
  (Bauer et al. 2016) covers.

## Parameters

- `frozen_fraction_limit` (default 0.5): the largest share of the window the PV may stay at one
  value before the data are rejected as frozen.
- `invalid_fraction_limit` (default 0.2): the largest share of invalid samples before the data are
  rejected.
- `lower_limit` (default none): the PV's physical lower limit; values below it are invalid.
- `upper_limit` (default none): the PV's physical upper limit; values above it are invalid.

## How to read the finding

"PV values are sound." or "PV stuck at the same value for 100% of the window." A rejected window
gives the status "Data not usable" and the CPM methods do not run: check the transmitter, its
communication and the signal in PlantCraft.

## Limits

- Calculated or low-resolution signals, and analysers that hold their last value, can look frozen
  without being so.
- Without limits, physically impossible values are not caught.
