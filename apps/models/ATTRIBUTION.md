# Third-party assets and libraries

Every third-party asset (font, icon, image, dataset) and every direct dependency
has a row here (AGENTS.md, "Clean room"). The PlantCraft Models mark (`docs/images/logo.svg`,
`frontend/public/favicon.svg`), the suite frame `@plantcraft/ui` (vendored package: tokens,
fonts setup, sidebar, help browser, brand marks, chart colours) is original work of the
PlantCraft authors (Apache-2.0).

## Fonts and icons (bundled, served offline)

| Asset | Source | License |
|---|---|---|
| IBM Plex Sans, IBM Plex Mono | `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono` (IBM) | SIL Open Font License 1.1 |
| Lucide icons | `lucide-react` | ISC |

## Modelica (in the runner image, `deploy/runner/Dockerfile`)

| Software | Source | License |
|---|---|---|
| OpenModelica 1.24.4 (omc), used as a separate program in its own container, never linked into this code | `openmodelica/openmodelica:v1.24.4-minimal` image, https://openmodelica.org | OSMC Public License 1.8 (OSMC-PL) / GPL 3 |
| Modelica Standard Library 4.0.0 (also ModelicaServices, Complex) | https://github.com/modelica/ModelicaStandardLibrary (commit `6626538a`) | BSD-3-Clause |
| OMChemSim (package `Simulator`: chemical components, thermodynamic packages, unit operations), fetched into the runner image, never copied into this repository | https://github.com/FOSSEE/OMChemSim (commit `26451297`), FOSSEE, IIT Bombay | BSD-3-Clause |
| Python 3 (runs the runner, standard library only) | Debian package | PSF License |

The class icons and documentation shown in the interface are drawn from the Modelica Standard
Library's own annotations at run time; none is copied into this repository.

## Frontend libraries

| Library | License |
|---|---|
| React, React DOM | MIT |
| Plotly.js (`plotly.js-cartesian-dist-min`), `react-plotly.js` | MIT |
| CodeMirror 6 (`@codemirror/*`, including `legacy-modes` for Modelica), Lezer (`@lezer/highlight`) | MIT |
| `@plantcraft/ui` (vendored package, PlantCraft authors) | Apache-2.0 |
| Vite, Vitest, TypeScript, jsdom (build and test only) | MIT |

## Python libraries

| Library | License |
|---|---|
| plantcraft-sdk (vendored wheel, PlantCraft authors) | Apache-2.0 |
| NumPy (simulation results), SciPy (optimization studies), pandas (through plantcraft-sdk) | BSD-3-Clause |
| pydantic | MIT |
| httpx | BSD-3-Clause |
| cryptography (through plantcraft-sdk) | Apache-2.0 or BSD-3-Clause |
| FastAPI, Starlette, Uvicorn | MIT / BSD-3-Clause |
| pytest, Ruff (development only) | MIT |
| Playwright for Python (e2e tests only, never in the image) | Apache-2.0 |

## Data

No third-party dataset is committed. The test plant (`plantcraft_sdk.testplant`, a port of
The Simulator's loop equations) is synthetic. The example models (`src/modelcraft/examples/`) are
original work of the PlantCraft authors (Apache-2.0), `PlantCraftProcess` included: it only uses
OMChemSim's classes by name; `PlantCraftTwin` is PlantCraft Twin's.
The runner answers in `tests/fixtures/` were recorded from OpenModelica on those examples (the
library index lists the MSL's class names and descriptions, BSD-3-Clause).
