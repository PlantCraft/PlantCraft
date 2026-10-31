# Requirements and recommended infrastructure

What a PlantCraft installation needs: the server, the compute workers, the computers that run
Notebooks locally, and how the disk grows. **Every number here is measured** on the machines named
in [How these numbers were measured](#how-these-numbers-were-measured), and is updated as the
load tests run; "estimate" marks the few that are not measured yet. For the bench behind the plant
sizes, see [Sizing the server](en/sizing.md).

## Short answer

| | Minimum (trial, a few apps) | Recommended (a plant area) | Large scale (a whole site) |
|---|---|---|---|
| Plant | demo or a pilot unit, up to 10 people at once | up to 8,000 signals, 2,000 loops, 30 people at once | 8,000 to 30,000 signals, 100 people at once (estimate) |
| Server CPU | 4 vCPU (x86_64 or ARM64) | 8 vCPU | 16 vCPU (estimate) |
| Server memory | 8 GB (12 GB with every app on) | 32 GB | 64 GB (estimate) |
| Server disk | 50 GB SSD | 1 TB SSD | 4 TB SSD, backups on another disk (estimate) |
| Compute workers | the one on the server | the one on the server, plus 1 machine when many people run models | 2 or more machines of 8 vCPU, 16 GB |
| Operating system | Linux with Docker 24+; macOS or Windows (Docker Desktop) for trials | Linux server (Ubuntu 22.04/24.04, RHEL 9 or alike) | Linux servers |

Why these numbers:

- **Below the minimum.** A 2 vCPU, 4 GB machine runs the demo with every app on only with
  **2 GB of swap**: without it the kernel stops the Historian, Models and Documents for lack of
  memory (0.6.0 load tests, 2026-10-30). With swap it took 10 analysis methods at once plus 20
  people in a 2.5 s round. Use it for trials only.
- **Memory.** With every app on and idle, the suite uses **4.5 GB** (16 containers, Windows with
  WSL 2) to **7.0 GB** (Mac mini, Docker Desktop, with two compute workers). At the bench's target
  scale the busiest containers peak at about 1 GB each (Analytics, PlantCraft, the Historian's
  database). 16 GB runs a plant area; 32 GB leaves room for the database cache, the page cache,
  backups and models running on the server's own worker.
- **CPU.** The Analytics round over 2,050 loops takes about 106 s on 4 vCPU with the server's own
  compute worker (27 s on a 12-core Mac mini). People at once are bound by CPU too: on 4 vCPU,
  shared with the simulated plant, 50 people open a page in 1.6 s at p95 and 100 people in 2.6 s
  (below). 8 vCPU keeps rounds short and pages quick while people work on the same machine.
- **People at once.** Measured with `ci/bench/load_users.py` on 4 vCPU, 16 GB, the demo plant
  plus 160 signals with 90 days of history: each person signs in as the demo's read-only
  visitor and opens the suite's screens one after another as a browser does (119 screens
  recorded with a browser, 19 API calls each, six at a time), with 5 to 15 s between screens;
  after 30 % of the screens they also ask a heavy question of the data (a trend of 2 to 8 signals
  over 7, 30 or 90 days, a signal's day as recorded or its 30 or 90 days, a dashboard's every
  panel over 7 or 30 days, a report over 30 days). With the fixes of 2026-10-27 (main of that day
  plus PlantCraft's connections kept, Analytics' queue answer kept 5 s, the Historian's read
  budget):

  | People at once | Screens/s | API calls/s | Screen p50 | Screen p95 | Heavy question p95 | Failed |
  |---:|---:|---:|---:|---:|---:|---:|
  | 10 | 0.62 | 13 | 0.2 s | 1.0 s | 0.1 to 2.2 s | 0.04 % |
  | 50 | 3.0 | 64 | 0.3 s | 1.6 s | 0.2 to 6.5 s | 0.06 % |
  | 100 | 5.6 | 120 | 0.7 s | 2.6 s | 0.7 to 10 s | 0.02 % |

  Before those fixes the same test gave a screen p95 of 0.8 s with 10 people, 8.5 s with 50 and
  20 s with 100: each PlantCraft request opened 20 to 40 SQLite connections, and every screen
  rebuilt Analytics' queue. The heaviest questions are reports and dashboards over 30 days
  (several panels each); trends and the Historian's 90 days stay under 1 s with 50 people. The
  failures are visitor screens that ask for something a visitor may not read (403). With 100
  people the 4 vCPU are full (PlantCraft 196 %, Analytics and its worker 230 %, the simulator
  and the collector 210 %).
- **On the Mac mini** (Apple silicon, 12 cores, Docker Desktop with 12 CPUs and 16 GB, the live
  demo with its plant and Analytics rounds running): the same test as the administrator (a visitor
  enters through "Enter the demo" and would take real visitors' places), the screens' calls to
  objects this install does not have left out (71 of 2,200):

  | People at once | Screen p50 | Screen p95 | Heavy question p95 | Failed |
  |---:|---:|---:|---:|---:|
  | 10, before the fixes | 19 s | 62 s | up to 60 s (timeouts) | 3 % (timeouts) |
  | 50, before the fixes | 60 s | 103 s | up to 190 s | 15 % (timeouts) |
  | 10, with the fixes | 0.3 s | 2.9 s | 0.1 to 5.5 s | 0.16 % |
  | 50, with the fixes | 2.2 s | 16 s | 1 to 19 s | 13 % (429, see below) |

  Docker Desktop's shared folders make each SQLite connection costly, so the connections kept by
  PlantCraft count more here than on Linux (`/api/assistant` alone went from 1 s to 0.13 s). With
  50 people the 429s are the public demo's limit per address (`PLANTCRAFT_PUBLIC_DEMO_RATE`, 600
  a minute) shared by all the test's people, who come from one address; real visitors each have
  their own. What is slow with 50 is Analytics: its web server is one process (219 % CPU with
  its rounds), and its screens' calls (`/link/api/queue` p95 12.5 s, widgets up to 25 s) wait for
  it. The Historian's peak memory went from 1.9 GiB of its 2 GiB to 0.7 GiB.
- **A public demo.** Up to 10 visitors at once on the demo machine keep every screen under about
  1 s at p95 with room for heavy questions; the measured ceiling on 4 vCPU is about 50 before
  screens pass 1.5 s. Limit what one visitor runs at once (a few requests in flight per app),
  not how many screens they open.
- **Disk.** The Historian's archive is what grows (below). An SSD matters: the archive and the
  databases read many small pages.

## The server

| Item | Requirement |
|---|---|
| Processor | x86_64 (`linux-amd64` bundle) or 64-bit ARM (`linux-arm64` bundle, also Apple silicon) |
| Docker | Docker Engine 24.0+ with the Compose plugin 2.24+ (Linux), or Docker Desktop (macOS, Windows) |
| Network | Inbound TCP 443 from the people who use it; outbound only to the plant's data sources |
| Nothing else | No Python, Node.js, compiler, registry or internet access |

### Disk for the software

| What | Size |
|---|---:|
| Offline bundle, compressed (one processor; with the Notebooks kits) | 1.1 GB without kits, about 1.8 GB with them |
| Docker images of one version, loaded | about 7.6 GB (every app, the Historian's database, the Modelica runner) |
| The same during an update (old and new version side by side, until the old one is pruned) | about 15 GB |
| Install folder without history (settings, the apps' databases, logs) | under 10 GB |

So 50 GB of free disk is the floor for the software alone; history and backups come on top.

Images of one version, amd64, as built on 2026-10-27 (unpacked; several share their base layers,
so the sum is more than the space they take together):

| Image | Unpacked | Compressed |
|---|---:|---:|
| `processcraft` (PlantCraft, with JupyterLite and Pyodide for Notebooks) | 735 MB | 180 MB |
| `postgres` (the Historian's database) | 639 MB | 160 MB |
| `modelcraft` (Models) | 614 MB | 141 MB |
| `linkcraft` (Analytics) | 530 MB | 126 MB |
| `histcraft` (Historian) | 531 MB | 113 MB |
| `dashcraft` (View) | 468 MB | 108 MB |
| `alarmcraft` (Alarms) | 423 MB | 97 MB |
| `processcraft-installer` | 359 MB | 88 MB |
| `simcraft` (the Simulator, demo only) | 244 MB | 51 MB |
| `processcraft-proxy` (Caddy) | 152 MB | 40 MB |
| `modelcraft-runner` (OpenModelica and the Modelica Standard Library) | 1,279 MB | 303 MB |
| `doccraft` (Documents, with its embedding model) | not built here (its model download needs the internet); part of the Mac mini's 7.6 GB | |

### Memory per container

Idle, every app on, Windows 11 with WSL 2 (i5-8500T, 24 GB): 16 containers, **about 4.5 GB**.
Idle on the Mac mini (Docker Desktop, two compute workers): **about 7.0 GB**.

Peak at the bench's target scale (8,000 signals, 2,050 loops, 4 vCPU and 16 GB):

| Container | Peak memory | Its limit (`.env`) |
|---|---:|---:|
| Analytics | 1.0 GB | 4 GB (`LINKCRAFT_MEMORY`) |
| PlantCraft | 1.0 GB | 4 GB (`PLANTCRAFT_MEMORY`) |
| Historian database | 1.0 GB | 2 GB (`HISTCRAFT_DB_MEMORY`) |
| Historian | 600 MB | 2 GB (`HISTCRAFT_MEMORY`) |
| Simulator (demo) | 320 MB | |
| Collector | 190 MB | |
| Every other app | under 150 MB each | |

For a large site, raise the limits of PlantCraft, Analytics and the Historian's database first
([install-offline.md](install-offline.md), the settings table).

## Compute workers

Analytics' algorithms and Models' simulations run on compute workers ([compute.md](compute.md)).
Every installation has one on the server. Add machines when tasks wait (Settings › Compute shows
the queue).

| | Requirement |
|---|---|
| A worker machine | 2 vCPU and 4 GB at least; 8 vCPU and 16 GB to take `large` tasks |
| Software | Docker as for the server; about **2.5 GB** of images (the gateway and the executors of the apps it runs) |
| Memory per worker | about **0.67 GB** idle (Analytics executor 618 MB, gateway 42 MB), plus what its tasks use |
| Network | outbound HTTPS to the server only; it opens no port |

Each task names its size; a worker takes only the sizes its machine has room for:

| Task size | CPUs | Memory |
|---|---:|---:|
| `small` (default) | 1 | 1 GB |
| `medium` | 2 | 4 GB |
| `large` | 4 | 16 GB |

A worker runs as many tasks at once as its cores less one, so an 8-core worker runs 7 small
tasks, or 3 medium, or 1 large.

## Computers that run Notebooks

Notebooks run in the browser or, with the kit, on the person's own computer ([en/notebooks.md](en/notebooks.md)).
Neither runs code on the server: they only read through API v1.

**In the browser.** A recent Chrome, Edge or Firefox; the first time it downloads **about
130 MB** (kept in the browser's cache). A tab may use 2 to 4 GB of memory, so 8 GB of RAM is
the floor for real work.

**The kit on the person's computer** (Python 3.12, JupyterLab, numpy, pandas, scipy, matplotlib,
built on 2026-10-27):

| System | Download | Installed | Files |
|---|---:|---:|---:|
| Windows 10/11 x64 | 144 MB | 433 MB | 17,800 |
| macOS on Apple silicon | 124 MB | 374 MB | 16,700 |
| Linux x64 | 173 MB | 537 MB | 18,700 |

Recommended client: 4 cores, 8 GB of RAM (16 GB for large data sets), 2 GB of free disk (the kit,
its notebooks and the data they keep). No administrator rights are needed: the kit installs in
the person's own folder.

## How the disk grows

- **The Historian archive** is what grows. Two measures:
  - The bench (a value read every second for every signal, compressed by deviation): about
    **1.4 bytes per value read**, that is **120 KB per signal per day**, about 1 GB a day for 8,000
    signals.
  - The Mac mini running the demo plant (4,800 signals over 8.3 days, 37.4 million values kept):
    1.7 GB on disk, **about 42 KB per signal per day**. Only about 290 MB of that is data; the
    rest is space the database has not reused yet (being looked at; it would bring this to about
    7 KB per signal per day).
  - A year at the bench's rate: **45 MB per signal**, about 350 GB for 8,000 signals. Real plants
    often keep fewer values (steady signals), and a 5 s scan divides it by five. Each point's
    retention (Historian › Settings) caps it.
- **Backups** live in the install folder by default: keep room for about **twice the
  Historian's size**, or point them to another disk. On the Mac mini: 5.2 GB of data, 13 GB of
  backups.
- **Everything else** (PlantCraft and the apps' databases, logs, notebooks, documents) stays
  under 10 GB for a plant area.

Administration › System health shows the free disk and, after a day, in how many days it fills;
under 30 days it warns the administrators.

## How these numbers were measured

Kept up to date by the tests: when a load test or bench changes a number, change it here and in
[en/sizing.md](en/sizing.md), with the date and the machine.

| Numbers | Machine | Date |
|---|---|---|
| Plant sizes, peak memory per container, Historian bytes per value | `make bench-suite`, 4 vCPU 16 GB VM and the 12-core Mac mini ([bench results](bench/results/)) | 2026-10-21 to 2026-10-25 |
| Idle memory, 16 containers | Windows 11, WSL 2, i5-8500T, 24 GB | 2026-10-26 |
| Idle memory with two workers, images of one version, worker images, data and backups, Historian on disk | Mac mini (Apple silicon), Docker Desktop, main `6c138de5` | 2026-10-26 |
| Image sizes, Notebooks kit sizes | amd64 build of main in a Linux container | 2026-10-27 |
| Offline bundle sizes | the signed 0.4.0 bundles | 2026-10-25 |
| People at once (10, 30, 60), requests per second, peak CPU and memory per container | `ci/bench/load_users.py`, 4 vCPU 16 GB x86_64 VM, main `507f57b` ([report](bench/results/vm-20261027T0130-users.md)) | 2026-10-27 |
| People at once as demo visitors with heavy questions (10, 50, 100), before and after the fixes of 2026-10-27 | `ci/bench/load_users.py --visitor --heavy 0.3`, same VM, main `f1b49c5` ([before](bench/results/vm-20261027T1220-users.md), [after](bench/results/vm-20261027T1300-users.md)) | 2026-10-27 |
| People at once on the Mac mini (10, 50), before and after the fixes of 2026-10-27 | `ci/bench/load_users.py --heavy 0.3`, Mac mini (12 cores, Docker Desktop 12 CPUs 16 GB), main `6bba1b1c` then `d697764d` ([before](bench/results/Macs-Mac-mini-20261027T1348-users.md), [after](bench/results/Macs-Mac-mini-20261027T1413-users.md)) | 2026-10-27 |
| Three hours at target scale: no restart, disk flat, Historian's Postgres WAL bounded at 1.5 GB (`max_wal_size` 2 GB), SQLite WALs about 100 MB in all, Analytics' database 1.5 GB (loop samples) | `ci/bench/soak.py --hours 3`, same VM, main `4d55afe` ([report](bench/results/vm-20261027-0500-soak.md)) | 2026-10-27 |
| Analytics round, signal checks and queue at target scale with the server's compute worker | `make bench-suite --scale target`, same VM, main `79df9e9` with the fixes of 2026-10-27 ([report](bench/results/vm-20261027-0321-target.md)) | 2026-10-27 |
