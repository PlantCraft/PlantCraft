# PlantCraft Historian and PlantCraft: who does what

> **Decided:** 2026-10-19 by the maintainer: PlantCraft Historian is the suite's data layer. It owns every
> connection to plant systems and every history; PlantCraft keeps people, assets, apps and the
> single API door. The contract between the two: [data-layer.md](data-layer.md).

## The split

| Concern | Owner |
|---|---|
| Users, sign-in, tokens, app access, audit log | PlantCraft (PlantCraft Historian verifies its tokens offline) |
| Assets, roles, plant map; the API v1 door apps call | PlantCraft |
| Connections to plant systems: PI Web API, OPC UA (live and Historical Access), CSV files; their credentials (encrypted) | **PlantCraft Historian** |
| History, per signal: read from the source (`source`), collected and archived here (`archive`), or both | **PlantCraft Historian** |
| Collection: scan, swinging-door compression, chunked archive, retention, compaction | **PlantCraft Historian** |
| Series apps compute (derived signals, `app-<app>:<name>`) | **PlantCraft Historian** stores them; apps write through PlantCraft (`PUT /api/v1/series`) |
| Pages: sources, points, archive health, trend of a point | **PlantCraft Historian** (`/hist/`), opened from the PlantCraft launcher |

Apps change nothing: they call PlantCraft's API v1 with their own token; PlantCraft decides
who may read, then asks PlantCraft Historian (`/hist/api/v1/data`, only with PlantCraft's own token).

## Network

```text
 PI Web API, OPC UA, ── plant network ── histcraft (serve: pages + API) ── apps network (internal: true) ── PlantCraft ── apps
 CSV folders                          └─ histcraft-collector (collect)                     (only door for apps)
                                              │
                                     histcraft-db (PostgreSQL, histdb network, no port)
```

- PlantCraft Historian is the only component on both networks. It talks to plant systems **read-only**: PI
  Web API with GET only; OPC UA with Read, Browse and HistoryRead only (`tests/test_read_only.py`).
  There is no route that writes to a plant system; derived series and laboratory results
  (`POST /api/v1/lab`, stored at their sampling time) stay in PlantCraft Historian.
- Two containers from one image (2026-10-22): `histcraft serve` (pages and API,
  `HISTCRAFT_COLLECTOR=off`) and `histcraft-collector` (`histcraft collect`, no port). Updating
  or restarting the server, or a heavy query, never stops the recording; the collector's health
  check is its heartbeat (`histcraft healthcheck`). Their database is PostgreSQL `histcraft-db`;
  without a database URL, two SQLite files in the data folder (tests, demos), and
  `histcraft serve` alone collects too (`HISTCRAFT_COLLECTOR=embedded`, the default).
- One collector per archive: a collector holds a lease while it writes (a PostgreSQL advisory
  lock on its own connection, or a `flock` beside the SQLite archive). A second one, embedded
  or not, waits as a standby and takes over within seconds when the first stops; a collector
  whose lease connection drops stops collecting, and its container restarts and waits.
  `histcraft housekeeping` is refused while a collector runs.
- Who writes what: the server writes the configuration (sources, points, settings) and the
  series apps compute; the collector writes collected values. Tests check it
  (`tests/test_suite_rules.py`).
- Passwords of sources are stored encrypted (Fernet); the key is a file of its own
  (`HISTCRAFT_SECRET_KEY_FILE`, else `<data dir>/secret.key`, mode 0600), never in the database.

## Modes

| Mode | Reads answer from | Default for |
|---|---|---|
| `source` | the plant source, on each request; nothing kept here | PI Web API, CSV (always) |
| `archive` | PlantCraft Historian's archive (collected on a scan), plus the current value | OPC UA, derived |
| `both` | the archive, and the source for what lies before the first archived value | |

A source has a default mode; a signal may override it. Live collection exists for OPC UA;
PI signals in `archive` mode are a gap (`docs/gaps.md`).

## What each value means (the archive's semantics)

- **Recorded values** (no `step`): the values the collector archived after compression, plus the
  current value held in the compressor (the snapshot), so a read up to now ends at the newest
  value. Gaps (connection lost, bad quality) are stored as a "no data" marker and never bridged.
- **With `step`**: for numbers, the time-weighted average over `[t, t + step)` of the signal
  rebuilt from the archive (straight lines between archived values, or steps for points marked
  `step`); `null` where no data covers the interval. For text, the label in effect at the end of
  the interval. This differs on purpose from v1's "mean of the samples in the interval": a
  compressed archive keeps few samples on a flat signal, and the plain mean would leave holes.
- **Signals recorded on change on a grid** (since plantcraft-sdk 0.8.3, the same rule as v1's
  step-hold): a text signal, or a tag whose last word is `SP`, `SETPOINT` or `MODE` (any case,
  `plantcraft_sdk.contract.recorded_on_change`), is rebuilt as steps and its last value holds,
  with no limit, until its next sample, a "no data" marker, `end` or now. A source writes such
  a signal only when it changes, so a setpoint left alone after the read's last sample stays
  on the trend instead of going `null`. Other signals still end at their last value.
- **Value**: `last` is the snapshot; `mean`, `min`, `max`, `std` are taken over the rebuilt
  signal in the window (time-weighted mean and standard deviation).

## Open points

- MQTT, Modbus TCP and SQL sources are read by the gateway (`docs/gateway.md`). Sparkplug B,
  OPC DA and store and forward from an OPC UA edge box are gaps (`docs/gaps.md`); the gateway's
  sources are buffered on disk while the collector is away (`docs/gateway.md`).
