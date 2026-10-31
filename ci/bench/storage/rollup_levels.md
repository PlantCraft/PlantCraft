# Daily and monthly rollups: a year's read and disk (H9)

`rollup_levels.py`, 2026-10-31, PostgreSQL 16 on the cloud test machine (4 vCPU). It writes 50
signals × 365 days × 940 archived values a day (17.2 million values, a chunk per signal and day)
and then reads one signal's year. The raw numbers are in `rollup_levels.json`.

| | Before (hourly rollups only, 0.5) | After (+ daily and monthly) | After, raw values kept 90 days |
|---|---|---|---|
| Year as a daily trend (365 cells), warm | 44 ms | 11 ms | 12 ms |
| Same, first read | 78 ms | 16 ms | 24 ms |
| Mean of 364 days (`/value`), warm | 41 ms | 7.5 ms | 9.5 ms |
| Days of the year with a value | 365 | 365 | 364 (the first day lacks its first hour) |
| The 364-day mean | 50.01397 | 50.01397 | 50.01397 |
| Raw values (`chunks`) | 117 MB | 117 MB | 29 MB |
| Hourly rollups | 55 MB | 55 MB | 55 MB |
| Daily and monthly rollups | 0 | 2.8 MB | 2.8 MB |
| Total | 172 MB | 175 MB | 86 MB |

- **Reads:** 4 times faster for a daily trend and 5.5 times faster for a year's mean. They read 365 daily rows (or 12 monthly and a few daily) in place of 8,760 hourly ones. The answers are the same to the last digit.
- **Disk:** the days and months add 1.6% to the rollups. Each one is 152 bytes with its index, and an hourly row is 126. `archive/forecast.py` (`ROW_BYTES`) estimates the Settings page's disk by retention with these sizes.
- **Retention:** with the raw values kept 90 days and the rollups kept a year, the archive halves, and the year still trends with the same mean. Before, the hourly rollups went with the raw values.
- **Build:** summing the days and months of a year for 50 signals took 3.2 s, once. After that, each housekeeping sums only the day that just closed.
