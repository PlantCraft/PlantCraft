<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="PlantCraft Historian"></p>

# PlantCraft Historian

The data layer of the [PlantCraft](https://github.com/PlantCraft/PlantCraft) suite: every
connection to plant systems and every history, in one place.

- **Connect** to PI Web API, OPC UA (live values and Historical Access) and CSV files,
  **read-only**: GET only toward PI; Read, Browse and HistoryRead only toward OPC UA. Source
  passwords are stored encrypted, with the key outside the database.
- **Choose, per signal, where its history comes from**: read from the source on each request
  (`source`, the default for PI and CSV), collected and archived here (`archive`, the default
  for OPC UA servers that keep no history), or both.
- **Collect and compress** with swinging-door trending: the rebuilt signal never strays more than
  a deviation you set per signal; on/off and text values keep every change exactly.
- **Archive** in compressed chunks (about 1.5 bytes per value read on a noisy signal) in
  PostgreSQL, merged hourly, partitioned by month, with retention per signal (a past month whose
  values are all past retention is dropped as one table).
- **Keep what apps compute**: an app's derived series (`app-<app>:<name>`, with the subject it
  describes and the kind of result it holds) are stored and read like any signal.
- **Serve** recorded values, time-weighted averages on a grid and aggregates in the shapes of
  PlantCraft API v1. Apps keep calling PlantCraft; PlantCraft asks PlantCraft Historian
  ([docs/data-layer.md](docs/data-layer.md)).
- **Pages** to add sources, browse a server and pick its variables, follow every signal's status
  and compression, and trend any signal.

See [docs/boundary.md](docs/boundary.md) for what PlantCraft Historian does and what stays in PlantCraft.
Its metadata is in [app.toml](app.toml) (the suite's app standard).

## How it fits the suite

```text
 plant network                       apps network (internal)
 PI Web API, OPC UA, CSV ── histcraft (pages + API + collector, /hist/) ── PlantCraft ── apps
                               │ histcraft-db (PostgreSQL)                 API v1 door
```

## Run it

```sh
python -m venv .venv && . .venv/bin/activate
make deps                                  # plantcraft-sdk from vendor/, then PlantCraft Historian
(cd frontend && npm ci && npm run build)   # the interface, served under /hist/

# In PlantCraft: PLANTCRAFT_APPS=histcraft=/hist/ processcraft --port 8060
export PLANTCRAFT_URL=http://127.0.0.1:8060
histcraft serve --port 8100                # http://127.0.0.1:8100/hist/ (collects too)
```

Then, as an admin: **Sources > Add source** (OPC UA, PI Web API or CSV), **Browse**, pick the
variables. In the suite, PlantCraft Historian runs as three services: `histcraft` (pages and API) and
`histcraft-collector` (the collector alone, so an update of the server never stops recording),
both from this repository's `Dockerfile` (`make image`), and `histcraft-db` from the pinned
`postgres` image;
`deploy/compose.histcraft.yaml` holds them for PlantCraft's `deploy/compose.yaml`.

| Variable | Default | Meaning |
|---|---|---|
| `PLANTCRAFT_URL` | `http://127.0.0.1:8060` | PlantCraft as PlantCraft Historian reaches it (signing keys, audit) |
| `PLANTCRAFT_PUBLIC_URL` | (same host) | PlantCraft as the browser reaches it, for sign-in |
| `HISTCRAFT_DATABASE_URL` | none (SQLite) | PostgreSQL, `postgresql://histcraft@histcraft-db:5432/histcraft` in the suite; without it two SQLite files (tests, demos) |
| `HISTCRAFT_DATABASE_PASSWORD_FILE` | none | File with the PostgreSQL password (a Docker secret) |
| `HISTCRAFT_DATA_DIR` | `var` (`/data` in the image) | The SQLite files, when there is no database URL |
| `HISTCRAFT_ROOT_PATH` | `/hist` | Path prefix the proxy forwards unchanged |
| `HISTCRAFT_COLLECTOR` | `embedded` | `off` when a separate `histcraft collect` runs (the suite's compose file: service `histcraft-collector`); only one collector writes an archive, a second one waits |
| `HISTCRAFT_SECRET_KEY_FILE` | `<data dir>/secret.key` | Key that encrypts source passwords (created 0600 on first use; back it up) |
| `HISTCRAFT_FLUSH_SECONDS`, `HISTCRAFT_CONFIG_SECONDS` | 5, 5 | How often the collector writes, and rereads its configuration |
| `HISTCRAFT_ARCHIVE_SECONDS` | 60 | How often the values written every few seconds move into the archive's chunks (reads see them either way) |
| `HISTCRAFT_OPCUA_TIMEOUT`, `HISTCRAFT_READ_BATCH` | 10, 500 | OPC UA request timeout (s), nodes per Read |
| `HISTCRAFT_QUERY_TIMEOUT` | 30 | Seconds a read of series may run in PostgreSQL before it is cancelled (HTTP 504) |
| `HISTCRAFT_READ_VALUES` | 4000000 | Values the series answers in flight may hold together; a read past it waits, then answers 503 (memory bound for many long reads at once) |
| `HISTCRAFT_SOURCE_CACHE_SECONDS` | 300 | How long recent reads of PI and OPC UA signals in `source` mode stay in memory; a refresh asks only for the newest minutes (0: off) |
| `HISTCRAFT_SECRET_<NAME>` | none | A source password from the environment instead of the encrypted store (`password_env`) |
| `HISTCRAFT_LOG_LEVEL` | `INFO` | Log level |

## Develop

`make test-fast` is the quick loop while working (no slow tier); `make ci` runs what CI runs: ruff, the frontend build and tests, and pytest (compression,
archive, reads, the collector against a real OPC UA test server, PI Web API, OPC UA Historical
Access and CSV sources against local stand-ins, the API against
`FakePlantCraft`, hostile inputs, architecture, read-only, offline). `make bench` times 2,000
signals at 1 s (`--database-url postgresql://...` on PostgreSQL); `make test-postgres` runs the
suite on PostgreSQL (`HISTCRAFT_TEST_DATABASE_URL`). Read [AGENTS.md](AGENTS.md) before changing
anything.

## How it is built

PlantCraft Historian is **vibe coded**: written almost entirely by [Claude Code](https://claude.com/claude-code)
(Anthropic's Claude Opus 5.5 model), directed by a process engineer who decides what to build,
reviews the results and owns every decision. We say so openly. It is how one person with an AI
agent can bring industrial software within reach of researchers and process engineers who would
never get a licence for it, and it is why the rules are strict: one standard for every module,
tests that fail on network access, junk input, upward imports and slow tests, oracles on public
data, and a security audit per stage ([AGENTS.md](AGENTS.md)). The suite is also meant to be
used with AI. More in PlantCraft's
[How we build](https://github.com/PlantCraft/PlantCraft/blob/main/docs/how-we-build.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [ATTRIBUTION.md](ATTRIBUTION.md).
