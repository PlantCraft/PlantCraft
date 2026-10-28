# Sizing the server

How big a machine the suite needs, from the numbers we measured. Every figure below comes from
`make bench-suite` (`ci/bench/suite_bench.py`, reports in `docs/bench/results/`) on the suite
0.3.0 with every app on, unless it says "estimate".

## Short answer

| Plant | Signals archived | Loops / assets | People at once | CPU | RAM | Disk for a year of history and its backups |
|---|---:|---:|---:|---:|---:|---:|
| Small (a unit, a pilot) | up to 1,000 | up to 250 | up to 10 | 4 vCPU | 8 GB | 150 GB |
| Medium (a plant area) | up to 8,000 | up to 2,000 | up to 30 | 4 to 8 vCPU | 16 GB | 1 TB |
| Large (a whole site) | 8,000 to 30,000 | 2,000 to 8,000 | 30 to 100 | 12+ vCPU | 32 GB | 4 TB (estimate) |

The medium row is the bench's "target" scale, measured on a 4 vCPU, 16 GB virtual machine and on
a 12-core Mac mini (Apple silicon). The small and large rows are estimates from those numbers: run the
bench on your own machine before you rely on them.

## What we measured (target scale: 8,000 signals, 2,050 loops)

| Step | 4 vCPU, 16 GB | 12-core Mac mini |
|---|---:|---:|
| Historian writing the archive | 29,000 values/s | 52,900 values/s |
| One hour of raw values for 8,000 signals (one request each 500) | 4.0 s, p95 478 ms | 3.2 s, p95 710 ms |
| A 24 h trend of one signal, p95 | 21 ms | 17 ms |
| Analytics: a round over every loop | 106 s on the compute worker (50 to 58 s before workers) | 27 s |
| Analytics: checking every signal's quality | 257 s on the compute worker (64 s before workers) | 40 s |
| A dashboard of 24 cards | 1.8 s | 1.0 s |
| PlantCraft with 4 processes, 16 people clicking at once | 178 requests/s | 433 requests/s, p95 104 ms |
| People at once opening pages (5 to 15 s between pages, a heavy question of the data after 30 % of them): page p95 | 10: 1.0 s, 50: 1.6 s, 100: 2.6 s | 10: 2.9 s, 50: 16 s (the live demo; Analytics' one web process is the limit) |

Peak memory per container at that scale (4 vCPU machine): Analytics 1.0 GB, PlantCraft 1.0 GB,
Historian database 1.0 GB, Historian 600 MB, Simulator 320 MB, collector 190 MB, every other app
under 150 MB. About 4.5 GB in all, so 8 GB is tight and 16 GB leaves room for the system,
the page cache and backups.

## Disk

- **The Historian archive** is what grows. On the bench's signals (a value read every second,
  compressed by deviation) it takes about 1.4 bytes per value read: about **1 GB a day for 8,000
  signals**, 350 GB a year. Real plants often compress better (steady signals keep few values),
  and a scan of 5 s instead of 1 s divides it by five. Each point's retention (Historian ›
  Settings) caps it.
- **Backups** live in the install folder too: keep room for about **twice the Historian's size**
  (a weekly full copy and the daily incremental ones), or point the backups to another disk.
- **Everything else** (PlantCraft and the apps' databases, logs, the bundle) stays under 10 GB.

The suite watches its own disk: Administration › System health shows the free space and, after a day,
in how many days the disk fills at the current pace. Under 30 days it tells the administrators in
Messages, before anything stops.

## Measure your own machine

```bash
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale small    # about 5 minutes
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale target   # about 15 to 30 minutes
```

For people at once, `python3 ci/bench/load_users.py --prefix ~/PlantCraft` adds 10, 30, 60 and
100 people in steps of 3 minutes and stops at the first step whose pages take over 3 s at p95.
Every call it makes is a read. `--heavy 0.3` adds a heavy question of the data after 30 % of the
pages (trends of 7 to 90 days, a signal's 30 or 90 days, a dashboard or report over 30 days),
`--visitor` signs in as the public demo's visitor, and `--seed-days 90` first gives 160 bench
signals 90 days of history. The screens it opens are recorded with a browser by
`ci/bench/record_pages.py` (`ci/bench/load_pages.json`).

The report lands in `docs/bench/results/` with the machine's name; `--compare` puts two reports
side by side. Run it when the suite is not in use: it writes test data and removes it at the end.
