# Stack

The libraries the suite is built on, by area: what we use, its version and licence, and where
we wrote something ourselves that a mature library could do instead. It is here to follow the
stack and to decide changes when one is worth it. Versions are the ones pinned in the 0.3.0
release (`deploy/requirements.lock`, `package-lock.json`, the image digests in the Dockerfiles);
the licence inventory for publishing is in `docs/publishing.md`.

Last reviewed: 2026-10-23.

## Languages and runtime

| What | Version | Licence | Where |
|---|---|---|---|
| Python | 3.13 (`python:3.13-slim-trixie`) | PSF | Every app's server |
| TypeScript | 5.8 | Apache-2.0 | Every interface |
| Node.js | 22 (build only) | MIT | Builds the interfaces; not in the images that run |

## Backend (web servers and API)

| Library | Version | Licence | Where |
|---|---|---|---|
| FastAPI | 0.148 | MIT | Every app's API and API v1 |
| Starlette | 1.9 | BSD-3 | Under FastAPI |
| Uvicorn | 0.54 | BSD-3 | The server process |
| Pydantic | 2.14 | MIT | Request and settings models |
| httpx | 0.28 | BSD-3 | API v1 client in the SDK, tests |
| requests | 2.34 | Apache-2.0 | PI Web API (with `requests-kerberos`, ISC) |
| itsdangerous | 2.2 | BSD-3 | Signed session cookie |

## Data and calculation

| Library | Version | Licence | Where |
|---|---|---|---|
| NumPy | 2.5 | BSD-3 | Methods and blocks, compression, alarms |
| pandas | 3.0 | BSD-3 | Series in the SDK, Analytics methods, exports |
| openpyxl | 3.1 | MIT | Plant map and configuration file in Excel |
| ReportLab | 5.0 | BSD-3 | Analytics' PDF reports |
| graphlib (standard library) | Python 3.13 | PSF | Order and checks of a block diagram |
| FMPy | 0.3.32 | BSD-2 | Runs FMUs (process models) in Analytics |
| lxml | 6.1 | BSD-3 | FMU descriptions in Analytics |
| OpenModelica (`omc`) | 1.24.4 | OSMC-PL / GPL-3.0 | Models' runner container, a separate program |

## Databases

| What | Version | Licence | Where |
|---|---|---|---|
| SQLite (standard library) | Python 3.13 | Public domain | Each app's own database |
| PostgreSQL | 17.11 | PostgreSQL | Historian's archive |
| psycopg + psycopg-pool | 3.3 | LGPL-3.0 | Historian's connection to PostgreSQL |

## Plant connections

| Library or tool | Version | Licence | Where |
|---|---|---|---|
| asyncua | 1.1.8 | LGPL-3.0 | OPC UA client (Historian) and server (Simulator) |
| Telegraf | as shipped by InfluxData | MIT | Historian's gateway: MQTT, Modbus TCP and SQL sources |

## Interface

| Library | Version | Licence | Where |
|---|---|---|---|
| React | 19.2 | MIT | Every interface |
| Vite | 7.3 | MIT | Build and dev server |
| Plotly.js (`plotly.js-cartesian-dist-min`) + `react-plotly.js` | 3.7 / 4.1 | MIT | Every chart; `@plantcraft/ui` gives the common look (`timeChart`) |
| React Flow (`@xyflow/react`) | 12.12 | MIT | Block diagram editor (`BlockEditor`, Analytics) |
| CodeMirror | 6 | MIT | Modelica and Python code editors (Models) |
| FullCalendar (`@fullcalendar/*`) | 6.1 | MIT | Desk's calendar: year, month, week, day and list; events made and moved by dragging |
| Tiptap (`@tiptap/*`, on ProseMirror) | 3.31 | MIT | Desk's notes: rich text, checklists and `#` mentions (only the free extensions) |
| Lucide (`lucide-react`) | 0.468 | ISC | Icons |
| Inter and JetBrains Mono (in `@plantcraft/ui`) | Fontsource 5.3 | OFL-1.1 | Fonts, bundled (no font service) |

## Sign-in and security

| Library or tool | Version | Licence | Where |
|---|---|---|---|
| cryptography | 50.0 | Apache-2.0 / BSD | Ed25519 keys, Fernet for source passwords, bundle signatures |
| PyJWT | 2.15 | MIT | Tokens between PlantCraft and the apps (`plantcraft_sdk.jwt`) |
| argon2-cffi | 25.1 | MIT | Passwords (Argon2id; older PBKDF2 hashes move over at sign-in) |
| joserfc | 1.7 | BSD-3 | OpenID Connect ID tokens: signature and claims (`directory/jose.py`) |
| ldap3 | 2.9 | LGPL-3.0 | Corporate sign-in with LDAP or Active Directory |

## Packaging and running

| Tool | Version | Licence | Where |
|---|---|---|---|
| Docker + Compose | 29 (installer CLI) | Apache-2.0 | One container per app, offline bundle |
| Caddy | 2.11 | Apache-2.0 | The suite's HTTPS proxy |
| Debian (`trixie-slim`) | 13 | Various (DFSG) | Base of the images |

## Tests and quality

| Tool | Version | Licence | Where |
|---|---|---|---|
| pytest | 8 | MIT | Every Python test |
| Vitest + jsdom | 5 / 26 | MIT | Interface tests |
| Playwright | 1.64 | Apache-2.0 | Browser journeys (`make e2e`) |
| Ruff | 0.17.1 | MIT | Python lint and format |
| ESLint | 9 | MIT | Interface lint |

## Written by us, and what could replace it

Parts we wrote ourselves although a library exists, with the verdict of the review on
2026-10-23. The three swaps it found worth it are done: passwords on Argon2id, tokens on PyJWT
and OpenID Connect tokens on joserfc (Authlib's JOSE library). The rest is **later** (only when
the trigger in the note happens) or **keep** (a library would add more than it removes).

| Ours | Where | Alternative | Verdict |
|---|---|---|---|
| Historian backup (`pg_dump`) | `processcraft/apps/operations.py` | pgBackRest (MIT) | **Later**: when the archive passes about 100 GB (already planned) |
| Historian archive partitions | `histcraft/archive/partitions.py` | pg_partman (PostgreSQL) | **Later**: if partition upkeep grows; compression and rollups stay ours |
| Data table (sort, search, filters, pages) | `ui/src/DataTable.tsx` | TanStack Table (MIT) | **Later**: when a list is too long for the browser; the fix then is paging on the server, which a library does not give |
| Translations (`t()`, JSON catalogues) | `processcraft/i18n`, `ui/src/i18n.ts` | i18next or FormatJS (MIT) | **Later**: when the interface needs a third language or plurals per language |
| SQLite stores and forward migrations | `sdk/python/plantcraft_sdk/server/store.py` (~170 lines) | SQLAlchemy Core + Alembic (MIT) | **Later**: if an app has to run on another database |
| Release signatures (Ed25519) | `processcraft/apps/release.py`, `deploy/bundle.sh` | minisign (ISC), Sigstore cosign (Apache-2.0) | **Later**: cosign only when releases are public; it needs internet, the bundle does not |
| Markdown renderer | `ui/src/Markdown.tsx` | `react-markdown` + `remark-gfm` (MIT) | **Keep**: small, writes no raw HTML, and draws our flow and stack diagrams |
| Product tour | `ui/src/Tour.tsx` | Driver.js (MIT) | **Keep**: five languages and the suite frame built in |
| Navigation between pages | `ui/src/nav.ts` (~60 lines) | React Router (MIT) | **Keep**: each app has a handful of pages |
| Block engine | `sdk/python/plantcraft_sdk/blocks` | pipefunc, PathSim (MIT) | **Keep**: decided 2026-10-22, the libraries were young |
| Schedules, job queue and worker pool | `linkcraft/engine` | APScheduler, Procrastinate (MIT) | **Keep**: it would take two libraries (and PostgreSQL for Procrastinate) to do what the app's SQLite does |
| Historian compression, chunks and rollups | `histcraft/archive` | TimescaleDB | **Keep**: swinging door is the plant historians' method, and TimescaleDB compression is under the Timescale Licence, not open source |
| Language model client | `processcraft/specialists/model.py` | Official SDKs, LiteLLM (MIT) | **Keep**: plain HTTP speaks both formats with no dependency; off by default |
| SBOM of an image | `sdk/python/plantcraft_sdk/sbom.py` | Syft (Apache-2.0) | **Keep**: Syft is already used when installed; ours is the offline fallback |
| PI Web API client | `histcraft/sources/pi_web_api.py` | None mature and open | **Keep** |
| Alarm engine (ISA-18.2 figures) | `alarmcraft/engine` | None mature and open | **Keep** |
| Control loop methods | `linkcraft/methods` | None mature and open in Python | **Keep**; public methods only |
