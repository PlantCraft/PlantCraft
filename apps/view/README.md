<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="PlantCraft View"></p>

# PlantCraft View

Plant dashboards, trends and reports, as an app of the
[PlantCraft](https://github.com/PlantCraft/PlantCraft) suite. In the suite's menu it is
called **View** (the formal module name stays PlantCraft View).

PlantCraft View puts the signals and assets of PlantCraft on screens anyone in the
plant can read: KPIs with limits, trends, bars and tables, refreshed on their
own, in full screen for a control room wall, or behind a read-only public link
for a colleague without an account.

- **Dashboards** of up to 30 panels on a 12-column grid: KPI (one value, with
  warning and alarm limits), trend (up to 12 signals, two units on two axes),
  bars and tables (last, mean, min and max over a window).
- **Panels name what they read** by PlantCraft signal id, by asset and role
  (`p-201` / `pv`), or by role of the dashboard's asset: one "Loop detail"
  dashboard then serves every asset of that kind, picked at the top of the page.
- **Trends** (`/trends`): pick signals, overlay them or stack them as subplots on one time
  axis, over the last hours or a fixed period, as means of an interval or as recorded; save a
  trend to reopen it, download its data as CSV. Everyone with access may save trends; the
  author or an editor changes them.
- **Folders** that say who sees and who edits their dashboards: everyone, or people and groups of
  the platform. A new dashboard starts empty, from a template built from the plant's assets (a
  loop detail, a unit overview) or from an exported file; **Config** keeps tags, the window it
  opens with, a shared cursor, a kiosk mode and the last 30 versions.
- **Reports** (`/reports`): a document of notes, the same panels and the period's events (alarms,
  Link's findings) over one period, made into a PDF every day, week or month and sent to people
  and groups in Messages; every PDF sent is kept on the report's **Sent** tab, and the coming
  sends show on Desk's calendar. Download PDF and Send now make one at any time.
- **Public links**: read-only, one dashboard each, revocable, shown once.
  `DASHCRAFT_PUBLIC_LINKS=false` turns them off.
- **Editing in place**: every panel has a live
  preview, and two editors saving at once get a conflict, not a lost change.

## How it fits the suite

PlantCraft View follows the suite's app standard (PlantCraft `docs/app-standard.md`): its
metadata lives in [`app.toml`](app.toml) (id `dashcraft`, prefix `/dash/`, port 8080, uid
10006), and it serves `/healthz`, `/api/meta`, `/api/help` and `assets/<id>` (the dashboards
that show one asset, linked from PlantCraft's asset page) like every app of the suite.

```text
browser ── proxy ─┬─ /       PlantCraft             users, sign-in, connections (PI, OPC UA), assets, signals
                  └─ /dash/  PlantCraft View  dashboards, cards, public links (own SQLite)
PlantCraft View ── PlantCraft API v1 (plantcraft-sdk) ──> assets, signals, series, values, audit
```

PlantCraft View never opens a historian or an OPC UA connection: all plant data
comes from the PlantCraft API v1 through `plantcraft_sdk.client`, and
assets live only in PlantCraft. People sign in at PlantCraft; PlantCraft View
verifies their token offline (`TokenVerifier`, app id `dashcraft`) and records
every change in PlantCraft's audit log.

The interface draws the suite's frame from `@plantcraft/ui` (vendored in `vendor/`): the
sidebar with PlantCraft View's pages, the other apps, Help (the guides of `docs/help` in folders) and
the user menu (theme, About, Sign out). Full screen and public links show the dashboard alone.

A saved dashboard is a published report: it reads with PlantCraft View's service
token (from an app key), so every viewer, and a public link, sees the same
numbers, and one read is shared by all viewers for `DASHCRAFT_CACHE_SECONDS`.
The pickers and the preview an editor uses while building a panel read with
the editor's own token, so PlantCraft's permissions decide what they can
put on a dashboard.

## Run it

```sh
python -m venv .venv && . .venv/bin/activate
make deps                                  # plantcraft-sdk from vendor/, then PlantCraft View
(cd frontend && npm ci && npm run build)   # the interface, served under /dash/

# In PlantCraft: PLANTCRAFT_APPS=dashcraft=/dash/ processcraft --port 8060,
# then an admin creates an app key for dashcraft (Settings, or POST /api/app-keys).
export PLANTCRAFT_URL=http://127.0.0.1:8060
export PLANTCRAFT_APP_KEY=...            # or PLANTCRAFT_APP_KEY_FILE=/path/to/key
dashcraft serve --port 8080               # http://127.0.0.1:8080/dash/
dashcraft check                           # settings, app key and PlantCraft reachable
dashcraft migrate-signals                 # saved cards from bare tags to API v1 signal ids (also at start)
```

Without an app key PlantCraft View still serves signed-in people (dashboards read
with their own token) but public links are off.

| Variable | Default | Meaning |
|---|---|---|
| `PLANTCRAFT_URL` | `http://127.0.0.1:8060` | PlantCraft as PlantCraft View reaches it |
| `PLANTCRAFT_PUBLIC_URL` | (same host) | PlantCraft as the browser reaches it, for sign-in |
| `PLANTCRAFT_APP_KEY`, `PLANTCRAFT_APP_KEY_FILE` | `<data dir>/dashcraft-app-key` | App key: dashboards read with PlantCraft View's service token |
| `DASHCRAFT_ROOT_PATH` | `/dash` | Path prefix the proxy forwards unchanged |
| `DASHCRAFT_DATA_DIR` | `var` (`/data` in the image) | SQLite database |
| `DASHCRAFT_PUBLIC_LINKS` | `true` | Editors may create read-only public links |
| `DASHCRAFT_CACHE_SECONDS` | `10` | How long one plant data read is shared by every viewer |
| `DASHCRAFT_HOST`, `DASHCRAFT_PORT` | `127.0.0.1`, `8080` (`0.0.0.0` in the image) | Bind address and port |

In the suite, PlantCraft View runs as the `dashcraft` service of PlantCraft's
compose file, built from this repository's `Dockerfile` (`make image`): uid
10006, read-only root filesystem, state only in `/data`, port 8080. `make package` builds the
signed `dashcraft-<version>.pcapp` for the Apps page:
The image carries its SPDX SBOM at `/app/sbom.json` (`python -m plantcraft_sdk.sbom`, at build time).
`make package PUBLISHER_KEY=<ed25519 key>` packs that SBOM (pass `SBOM=<file>` to use your own) and calls PlantCraft's
`deploy/package.sh` (`PLANTCRAFT_DIR`, default `../..`, the repository root).

## Develop

`make test-fast` is the quick loop while working (no slow tier); `make ci` runs what CI runs: ruff, the frontend build and tests, and pytest
(model, store, panel reads, API against `FakePlantCraft`, public links, hostile
inputs, a pandas oracle for aggregations, architecture, offline). `make e2e`
runs the Playwright journeys. Read [AGENTS.md](AGENTS.md) before changing
anything.

## How it is built

PlantCraft View is **vibe coded**: written almost entirely by [Claude Code](https://claude.com/claude-code)
(Anthropic's Claude Opus 5.5 model), directed by a process engineer who decides what to build,
reviews the results and owns every decision. We say so openly. It is how one person with an AI
agent can bring industrial software within reach of researchers and process engineers who would
never get a licence for it, and it is why the rules are strict: one standard for every module,
tests that fail on network access, junk input, upward imports and slow tests, oracles on public
data, and a security audit per stage ([AGENTS.md](AGENTS.md)). The suite is also meant to be
used with AI. More in PlantCraft's
[How we build](https://github.com/PlantCraft/PlantCraft/blob/main/docs/how-we-build.md).

## License

Apache-2.0 ([LICENSE](LICENSE)). Third-party assets: [ATTRIBUTION.md](ATTRIBUTION.md).
