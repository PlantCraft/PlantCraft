# Suite bench: the whole suite at plant scale

`ci/bench/suite_bench.py` measures an installed suite (Docker, `install.sh`) end to end at the
size of a real plant, and saves one report per run in `results/` so runs on different days and
machines can be compared. It never runs in GitHub CI.

## Run it

```bash
make e2e-bundle                         # a fresh stack from the checkouts (or use an installed one)
make bench-suite                        # target scale on dist/e2e-bundle/install
make bench-suite BENCH_PREFIX=~/PlantCraft BENCH_SCALE=small
python3 ci/bench/suite_bench.py --compare   # every saved report, one line each
```

`python3 ci/bench/suite_bench.py --help` lists the options (`--loops`, `--extra`, `--hours`,
`--twins`, `--keep`, `--skip-seed`, `--yes`). Only the Python standard library is used, so the
system `python3` of any machine runs it; it needs `docker compose` for the installation and its
admin password (`data/initial-admin-password` or `PLANTCRAFT_ADMIN_PASSWORD`).

| Scale | Loops | Signals | Archive | Twins | Time here (4 CPUs) |
|---|---|---|---|---|---|
| `small` | 200 | 800 | 24 h | 10 | a few minutes |
| `target` | 2,000 | 8,000 | 24 h | 50 | about 40 min (most of it the archive seed) |
| `stress` | 5,000 | 20,000 | 24 h | 100 | over an hour |

The bench adds a unit `BENCH` with its areas and loops, a Historian source `bench` (disabled: the
collector never polls it) and its archive, a dashboard and twins, and removes all of it at the end
(`--keep` leaves it). Run it on a test installation; on a plant's own installation run it outside
working hours, since it loads every container.

## What it measures

1. **Historian archive write**: `hours` of one value per 30 s per signal through the real
   compressors into PostgreSQL, written per simulated minute, then compacted
   (`ci/bench/hist_seed.py`, run inside the Historian container).
2. **Plant map**: preview and import of the assets and signals (`/api/map`).
3. **API v1 reads** (PlantCraft forwarding to Historian): all signals in batches of 500 over the
   last hour (raw) and the whole window on a 60 s grid; 100 single-signal 24 h trends. The
   same batches straight from the Historian (`/hist/api/v1/series`, labels `..._direct`), as
   apps read with `plantcraft-sdk` 0.13.0.
4. **Analytics rounds**: two monitoring rounds over every loop (sync, read, analyse, publish).
   Then **Analytics' queue**: `--queue-jobs` executions (1000 by default) queued at once on the
   bench loops; the report gives the drain time, executions per second, the longest wait, the
   failures, the engine's peak CPU and memory, and whether `/api/ops/metrics` carries the queue
   (what PlantCraft's watch reads to tell the admins when it does not drain).
5. **View**: a dashboard of 12 trend and 12 KPI cards, every card read once.
6. **Analytics' model algorithms**: copies of the demo's model algorithm on bench loops; the share it ran on per minute.

Peak CPU % and memory of each container are sampled through the run (`containers`,
`cpu_by_phase`). The report keeps the machine (CPUs, memory, Docker) and app revisions.

## On another machine (the Mac mini)

From a PlantCraft checkout on that machine, against its installation:

```bash
git pull
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale small    # first, a few minutes
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale target
```

Commit the new files in `docs/bench/results/` (or send them) to compare with the others. Images
built for another CPU (amd64 on an Apple Silicon Mac) run emulated and are slower: the report's
`machine.docker` says which architecture Docker runs.

## Soak: days on one build (`ci/bench/soak.py`)

The bench says how fast; the soak says whether the suite stays up, flat and fresh when left
running for days. It adds nothing: it watches the installation as it is, so run it right after a
target bench kept its data, which keeps Analytics and the Historian busy at plant scale.

```bash
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale target --keep --yes
nohup caffeinate -i python3 ci/bench/soak.py --prefix ~/PlantCraft --hours 72 > ~/soak.log 2>&1 &
python3 ci/bench/soak.py --prefix ~/PlantCraft --report     # the verdict so far, any time
python3 ci/bench/soak.py --prefix ~/PlantCraft --release    # end it early
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale target --cleanup   # bench data out
```

- **One build.** `data/deploy-hold` holds the Mac mini's automatic deploys until the soak ends
  (`ci/macmini/suite-deploy` skips while it is in date; CI still runs and builds the images; the
  next push of each repository after the soak deploys it). `--no-hold` leaves deploys on.
- **Probes** every minute, as a person uses the suite: `/api/me`, a batch read of 500 signals
  over the last hour, the newest value of 20 live signals (how old it is) and a card of the bench
  dashboard. They go to `data/soak/probes.jsonl` as they happen; a soak stopped by a reboot
  resumes when run again with the same command.
- **The suite's own health** from the Historian's `system` source (docs/operations.md, section 4):
  up, restarts, memory, latency, errors, queues and free disk of every container, every minute.

The verdict, in `data/soak/report.md` (refreshed every 6 h) and in `results/<host>-<time>-soak.md`
at the end:

| Check | Pass | Warn | Fail |
|---|---|---|---|
| Restarts of a container | none | | any |
| Up (running and healthy) | 99.5 % of the time | | less |
| Memory after the first hour | under +10 %/day | +10 to +25 %/day | over +25 %/day |
| Oldest item of a work queue | 30 min at most | | longer |
| Disk | full in 30 days or more | sooner | |
| Probes | 0.5 % failed at most | | more |
| Newest live value, p95 | 2 min old at most | older | |

## Months old in a few hours (`ci/bench/age.py`)

A soak of 72 hours never reaches what grows for months: Analytics keeps 90 days of every
monitoring round (a row per loop every 10 min) and of every signal check (a row per signal every
15 min), the Historian keeps everything. Running the clock faster does not get there either: the
work grows with it (at 10x the 106 s round of 2,000 loops is due every minute, so the suite would
only be measured drowning). So the history is written first, at the speed of the machine through
the apps' own stores, and the suite is then measured at the speed of the plant, in steps:

```bash
python3 ci/bench/suite_bench.py --prefix P --scale target --keep --yes   # the bench plant
python3 ci/bench/age.py --prefix P --months 0     # step 0, as it is
python3 ci/bench/age.py --prefix P --months 3     # writes the past up to 3 months, then measures
python3 ci/bench/age.py --prefix P --months 6     # adds months 4 to 6 only
python3 ci/bench/age.py --compare                 # the steps side by side
python3 ci/bench/soak.py --prefix P --hours 24    # a day at the plant's speed on the aged suite
```

- **Historian** (`hist_age.py`, in its container): the bench signals' values back to the step's
  age, `--rate` per signal per day (940: what the demo plant keeps after compression), one chunk
  per signal per hour, compacted per day, every month rewritten once closed, rollups built.
- **Analytics** (`link_age.py`, in its container): the newest round's loop health and the newest
  check's verdicts copied back once per past round, up to the 90 days Analytics keeps.
- **Measures**, the same at every step: the hourly maintenance of both, the reads behind the
  history pages (a loop's month, the portfolio's week, the checks' week, a signal's month, a
  signal's whole history, 500 signals at once), every page of `load_pages.json`, a signal check
  and a monitoring round, `--users` people at once, each database's size, each container's
  memory; `--backup` also times `install.sh --backup`.

Reports in `<prefix>/data/age/` and `results/<host>-<time>-age-<months>m.md`. Disk: about 1 GB a
month of Historian per 8,000 signals, and Analytics' plateau (90 days) on top.

### A frozen suite for the long tests (`ci/bench/frozen.sh`)

The suite in development takes every merge; the long tests need one that does not. On the same
machine, a second installation from a bundle, under its own Compose project and port:

```bash
make bundle                                                  # at the commit to test
ci/bench/frozen.sh install dist/processcraft-*-bundle ~/PlantCraft-carga 8443
ci/bench/frozen.sh check ~/PlantCraft-carga                # still on the images installed?
```

Its containers keep the images they were created with when the suite in development retags the
same names; `check` says so. Two suites at plant scale need about twice the memory: keep the one
in development on the demo plant while the frozen one carries the bench.

## Extreme load on the Historian (`ci/bench/extreme.py`)

What many methods reading at the same moment do to the Historian, while people use the suite
(0.6.0 scenarios). It adds nothing to the plant: it starts Analytics' loop round and signal
checks together, as their schedules do at the top of the hour, and at that moment `--methods`
other reads of what a round reads (the plant's signals over `--hours`, raw or in means of
`--step` s, four requests at once, as Analytics does), while `--people` open a trend, a display's
newest values and Analytics' overview every few seconds.

```bash
python3 ci/bench/extreme.py --prefix P --scenario C1           # today's load
python3 ci/bench/extreme.py --prefix P --scenario C2           # ten times the methods
python3 ci/bench/extreme.py --prefix P --scenario C2 --step 60 # the methods read means
python3 ci/bench/extreme.py --compare
```

The report gives each caller's p50/p95 and statuses (503: the read budget was full; 504:
PlantCraft gave up), how long each container stayed at a full core, and the rounds' times, in
`results/<host>-<time>-extreme-<scenario>[-label].md`. To imitate a smaller machine, set the
containers' limits in the installation's `.env` (`HISTCRAFT_CPUS`, `HISTCRAFT_MEMORY`,
`LINKCRAFT_CPUS`...) or run it in a virtual machine of that size.

First runs (cloud, 4 CPUs, demo plant with its 48 h archive, 167 plant signals x 24 h):

| | round s | checks s | 10 methods s | person trend p95 s | Historian at a full core s |
|---|---|---|---|---|---|
| C1, today | 7 | 11 | | 0.1 | 4 |
| C2, 10x methods | 30 | 34 | 26 | 3.4 | 25 |
| C2, means of 60 s | 13 | 18 | 12.5 | 0.8 | 8 |
| C2, times written at once (SDK fix) | 16 | 18 | 10 | 1.6 | 8 |
| C2, SDK fix + Historian in 2 processes | 10 | 13 | 6.5 | 0.4 (display) | 4 |

## PlantCraft alone: 50,000 signals and 50 apps (`ci/bench/platform_scale.py`)

Scale review E14 (2026-10-25). It runs from a checkout, with no Docker: PlantCraft in one
process over a recorded source of 50,000 signals, and 50 stub suite apps doing their start and
one round at once (token, contributions with `[permissions]`, the signal list in pages and again
with ETags, a 500-signal batch, 100 results, audit, and a refused route).

    python ci/bench/platform_scale.py                          # 50,000 signals, 50 apps
    python ci/bench/platform_scale.py --signals 5000 --apps 10 --check

First runs, 4 CPUs (reports in `docs/bench/results/*-platform-*`):

| | before | after |
|---|---|---|
| all 50 apps' round at once | 571 s | 164 s |
| one 50,000-signal catalog | ~40 s (a registry query per tag) | 0.2 s, built once per 2 s |
| the list in 10 pages, p50 | 172 s | 21 s |
| a 500-signal batch alone | 2.2 s | 1.1 s |

What remains is one Python process doing 50 batches of 500 signals over a recorded file at
once: light calls (results, audit) then wait behind them. With the Historian (`HISTCRAFT_URL`)
the batches are read there, and `PLANTCRAFT_WORKERS` spreads the rest over processes.
