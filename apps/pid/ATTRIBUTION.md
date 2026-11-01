# Third-party assets and libraries

Every third-party asset (font, icon, image, dataset) and every direct dependency
has a row here (AGENTS.md, "Clean room"). The PlantCraft PID mark (`docs/images/logo.svg`,
`frontend/public/favicon.svg`), the suite frame `@plantcraft/ui` (vendored package: tokens,
fonts setup, sidebar, help browser, brand marks, chart colours) is original work of the
PlantCraft authors (Apache-2.0).

## Fonts and icons (bundled, served offline)

| Asset | Source | License |
|---|---|---|
| IBM Plex Sans, IBM Plex Mono | `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono` (IBM) | SIL Open Font License 1.1 |
| Lucide icons | `lucide-react` | ISC |

## Frontend libraries

| Library | License |
|---|---|
| React, React DOM | MIT |
| Plotly.js (`plotly.js-cartesian-dist-min`), `react-plotly.js` | MIT |
| `@plantcraft/ui` (vendored package, PlantCraft authors) | Apache-2.0 |
| Vite, Vitest, TypeScript, jsdom (build and test only) | MIT |

## Python libraries

| Library | License |
|---|---|
| plantcraft-sdk (vendored wheel, PlantCraft authors) | Apache-2.0 |
| NumPy (suggested limits), pandas (through plantcraft-sdk) | BSD-3-Clause |
| pydantic | MIT |
| httpx | BSD-3-Clause |
| cryptography (through plantcraft-sdk) | Apache-2.0 or BSD-3-Clause |
| FastAPI, Starlette, Uvicorn | MIT / BSD-3-Clause |
| pytest, Ruff (development only) | MIT |
| Playwright for Python (e2e tests only, never in the image) | Apache-2.0 |

## Data

One third-party drawing is committed, for the drawing reader's tests:
`tests/files/dexpi-C01V01-HEX.EX02.pdf`, the example P&ID "C01V01-HEX.EX02" of the DEXPI
Training Test Cases (DEXPI initiative, https://gitlab.com/dexpi/TrainingTestCases), licensed
CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/); unchanged. Its DEXPI XML is committed too,
gzipped and otherwise unchanged, as `tests/files/dexpi-C01V01-HEX.EX02.xml.gz`. No other third-party
dataset is committed. The test plant (`plantcraft_sdk.testplant`, a port of
The Simulator's loop equations) is synthetic.
