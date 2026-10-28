<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="PlantCraft Alarms"></p>

# PlantCraft Alarms

Alarm management for the plant, as an app of the
[PlantCraft](https://github.com/PlantCraft/PlantCraft) suite.

PlantCraft Alarms turns plant values and what the other apps report into alarms, by rules, and
tells the right person once. It is built around the public alarm management lifecycle of ISA-18.2
and the guidance of EEMUA 191, with the grouping, inhibition and silences of public alerting tools.

- **Rules**: a value beyond a limit (high-high, high, low, low-low, with deadband and on/off
  delays), no data, another app's result, or an event another app reports so many times within
  a window ("Analytics found the loop critical 3 times in an hour", "a stiction finding still open
  after a day"). One rule covers a signal, some assets or every asset under a unit, and makes one
  alarm per asset. It makes an **alarm** (acknowledged, counted in performance) or an **alert**.
  Each rule carries its rationalization (cause, consequence, corrective action).
- **Events**: everything the apps reported to PlantCraft (its events), kept 30 days, with the
  rules that counted each event; **Create a rule** starts one from an event. Events notify
  nobody.
- **Notify, without a flood**: each rule says who hears (the schedule's owner by default), in
  PlantCraft's Messages and by email, with hours, reminders and escalation. Its alarms are
  gathered into one message, nobody gets more than 6 an hour, and a failed Analytics monitor holds
  back the alarms of its loops. Silences hold messages back during a planned shutdown.
- **Alarms**: every alarm in one table, most urgent first, refreshed every 5 seconds (needs
  attention, unacknowledged or all; only mine). A row opens the alarm with its value, its history
  and the messages sent about it. Operators acknowledge one or all (also from the message), shelve a
  nuisance alarm with a reason, and engineers take an alarm or a whole rule out of service. The
  ISA-18.2 states (unacknowledged, acknowledged, returned unacknowledged, shelved, out of service,
  normal).
- **Performance**: from the Overview, alarm performance over 24 hours, 7 or 30 days against the
  ISA-18.2 and EEMUA 191 targets (alarms per hour and per 10 minutes, floods, the most frequent,
  chattering and stale alarms, priority distribution, time to acknowledge), and the targets.
- **Try before saving**: any rule, as written, runs over the plant's recent history (or the
  events that came in) and says how many alarms and messages it would have made.
- **Published to the suite**: an `alarm_state` result on each asset (or signal), events
  `alarmcraft.alarm.raised` and `.cleared`, the daily monitoring run and the evaluation schedule.

## How it fits the suite

PlantCraft Alarms follows the suite's app standard (PlantCraft `docs/app-standard.md`): its
metadata lives in [`app.toml`](app.toml) (id `alarmcraft`, prefix `/alarm/`, port 8110, uid
10009), and it serves `/healthz`, `/api/meta`, `/api/help` and `assets/<id>` (the alarms of one
asset).

```text
browser ── proxy ─┬─ /        PlantCraft         users, sign-in, assets, signals, results, events
                  ├─ /hist/   HistCraft            connections and history
                  └─ /alarm/  PlantCraft Alarms  alarms, occurrences, journal (own SQLite)
PlantCraft Alarms ── PlantCraft API v1 (plantcraft-sdk) ──> assets, signals, series;
                                                    results, events, runs, schedules, audit
```

PlantCraft Alarms never opens a historian, an OPC UA server or any plant system, and never
writes to one: it reads series through PlantCraft API v1 and informs; the operator acts in the
control system. People sign in at PlantCraft; Alarms verifies their token offline and records
every change in PlantCraft's audit log. Alarms are evaluated with Alarms' service token (from an
app key), so they keep running when nobody has the page open.

## Run it

```sh
python -m venv .venv && . .venv/bin/activate
make deps                                  # plantcraft-sdk from vendor/, then PlantCraft Alarms
(cd frontend && npm ci && npm run build)   # the interface, served under /alarm/

# In PlantCraft: list alarmcraft=/alarm/ in PLANTCRAFT_APPS, then an admin creates an app key
# for alarmcraft (Apps page, or POST /api/app-keys).
export PLANTCRAFT_URL=http://127.0.0.1:8060
export PLANTCRAFT_APP_KEY=...            # or PLANTCRAFT_APP_KEY_FILE=/path/to/key
alarmcraft serve --port 8110               # http://127.0.0.1:8110/alarm/
alarmcraft check                           # app key and PlantCraft reachable
```

| Variable | Default | Meaning |
|---|---|---|
| `PLANTCRAFT_URL` | `http://127.0.0.1:8060` | PlantCraft as Alarms reaches it |
| `PLANTCRAFT_PUBLIC_URL` | (same host) | PlantCraft as the browser reaches it, for sign-in |
| `PLANTCRAFT_APP_KEY`, `PLANTCRAFT_APP_KEY_FILE` | `<data dir>/alarmcraft-app-key` | App key: the monitor reads the plant and publishes |
| `ALARMCRAFT_ROOT_PATH` | `/alarm` | Path prefix the proxy forwards unchanged |
| `ALARMCRAFT_DATA_DIR` | `var` (`/data` in the image) | SQLite database |
| `ALARMCRAFT_MONITOR` | `true` | Evaluate the alarms in the background |
| `ALARMCRAFT_CYCLE_SECONDS` | `10` | Seconds between evaluations (at least 1) |
| `ALARMCRAFT_DATA_LAG_SECONDS` | `5` | How far behind now the newest values are read |
| `ALARMCRAFT_HOST`, `ALARMCRAFT_PORT` | `127.0.0.1`, `8110` (`0.0.0.0` in the image) | Bind address and port |

In the suite, PlantCraft Alarms runs as the `alarmcraft` service of PlantCraft's compose
file, built from this repository's `Dockerfile` (`make image`): uid 10009, read-only root
filesystem, state only in `/data`, port 8110. The image carries its SPDX SBOM at
`/app/sbom.json`; `make package` builds the signed `alarmcraft-<version>.pcapp` with
PlantCraft's `deploy/package.sh`.

## Develop

`make test-fast` is the quick loop while working (no slow tier); `make ci` runs what CI runs: the app standard check, ruff, the frontend build and tests, and
pytest (evaluation and performance, the API and the monitor against `FakePlantCraft` with
The Simulator's loops, hostile inputs, architecture, offline). `make e2e` runs the Playwright
journeys. Read [AGENTS.md](AGENTS.md) before changing anything.

## How it is built

PlantCraft Alarms is **vibe coded**: written almost entirely by [Claude Code](https://claude.com/claude-code)
(Anthropic's Claude Opus 5.5 model), directed by a process engineer who decides what to build,
reviews the results and owns every decision. We say so openly. It is how one person with an AI
agent can bring industrial software within reach of researchers and process engineers who would
never get a licence for it, and it is why the rules are strict: one standard for every module,
tests that fail on network access, junk input, upward imports and slow tests, oracles on public
data, and a security audit per stage ([AGENTS.md](AGENTS.md)). The suite is also meant to be
used with AI. More in PlantCraft's
[How we build](https://github.com/PlantCraft/PlantCraft/blob/main/docs/how-we-build.md).

## License

Apache-2.0 ([LICENSE](LICENSE)). Third-party software: [ATTRIBUTION.md](ATTRIBUTION.md).
