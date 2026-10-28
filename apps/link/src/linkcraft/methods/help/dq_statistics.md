# Descriptive statistics

## What it detects

Nothing to judge: it describes the raw PV samples of the window (count, mean, standard
deviation, minimum, maximum, 5th and 95th percentiles) so a person can check the data are what
they expect (range, unit, scale). Part of the data quality gate, but it never blocks.

## Reference

- None: standard descriptive statistics.

## Parameters

This method has no parameters.

## How to read the finding

"8640 raw PV samples." Look at the metrics: a mean or range far from the expected values points
to a wrong signal, unit or scaling in PlantCraft.

## Limits

- Describes the data; does not judge whether they are good or bad.
