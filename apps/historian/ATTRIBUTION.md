# Third-party assets and libraries

Every third-party asset (font, icon, image, dataset) and every direct dependency
has a row here (AGENTS.md, "Clean room"). The PlantCraft Historian mark (`docs/images/logo.svg`,
`frontend/public/favicon.svg`), the suite frame `@plantcraft/ui` (vendored
package: tokens, fonts, sidebar, help browser, brand marks, chart colours) is original work of
the PlantCraft authors (Apache-2.0).

## Fonts and icons (bundled, served offline)

| Asset | Source | License |
|---|---|---|
| IBM Plex Sans, IBM Plex Mono | `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono` (IBM) | SIL Open Font License 1.1 |
| Lucide icons | `lucide-react` | ISC |

## Frontend libraries

| Library | License |
|---|---|
| `@plantcraft/ui` (vendored, PlantCraft authors) | Apache-2.0 |
| React, React DOM | MIT |
| Plotly.js (`plotly.js-cartesian-dist-min`), `react-plotly.js` | MIT |
| Vite, Vitest, TypeScript, jsdom (build and test only) | MIT |

## Python libraries

| Library | License |
|---|---|
| plantcraft-sdk (vendored wheel, PlantCraft authors) | Apache-2.0 |
| NumPy, pandas | BSD-3-Clause |
| requests, requests-kerberos (PI Web API source; Kerberos only with the `kerberos` extra) | Apache-2.0 / ISC |
| openpyxl, et-xmlfile (Excel imports) | MIT |
| pydantic | MIT |
| httpx | BSD-3-Clause |
| cryptography (through plantcraft-sdk) | Apache-2.0 or BSD-3-Clause |
| FastAPI, Starlette, Uvicorn | MIT / BSD-3-Clause |
| asyncua (OPC UA client; the collector only) | LGPL-3.0 (used unmodified as a library, not copied) |
| psycopg, psycopg-pool (PostgreSQL client; `psycopg-binary` bundles libpq) | LGPL-3.0 (used unmodified as a library, not copied); libpq: PostgreSQL License |
| zstandard (the archive's chunks; bundles the zstd library) | BSD-3-Clause; zstd: BSD-3-Clause |
| PostgreSQL (`postgres` image, the `histcraft-db` container; run, not linked) | PostgreSQL License |
| pytest, Ruff (development only) | MIT |
| Playwright for Python (e2e tests only, never in the image) | Apache-2.0 |

## Data

No third-party dataset is committed. The test OPC UA server (`tests/opcua_server.py`) and the
benchmark's signals are synthetic.
