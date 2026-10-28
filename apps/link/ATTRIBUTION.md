# Third-party assets and libraries

Every third-party asset (font, icon, image, dataset) and every direct dependency
has a row here (AGENTS.md, "Clean room"). The PlantCraft Analytics mark (`docs/images/logo.svg`,
`frontend/public/favicon.svg`) and the suite frame `@plantcraft/ui` (vendored package: tokens,
fonts setup, sidebar, help browser, brand marks, chart colours) are original work of the
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
| React Flow (`@xyflow/react`) | MIT |
| CodeMirror 6 and Lezer (`@codemirror/*`, `@lezer/highlight`; the Python editor of blocks and algorithms) | MIT |
| Vite, Vitest, TypeScript, jsdom (build and test only) | MIT |

## Python libraries

| Library | License |
|---|---|
| plantcraft-sdk (vendored wheel, PlantCraft authors) | Apache-2.0 |
| NumPy, pandas | BSD-3-Clause |
| pydantic | MIT |
| httpx | BSD-3-Clause |
| cryptography (through plantcraft-sdk) | Apache-2.0 or BSD-3-Clause |
| FastAPI, Starlette, Uvicorn | MIT / BSD-3-Clause |
| ReportLab | BSD-3-Clause |
| FMPy (runs FMUs) | BSD-2-Clause |
| lxml (FMPy reads `modelDescription.xml`) | BSD-3-Clause |
| attrs, lark, msgpack (FMPy's dependencies) | MIT / MIT / Apache-2.0 |
| pytest, Ruff (development only) | MIT |
| Playwright for Python (e2e tests only, never in the image) | Apache-2.0 |

## Built-in models (`fmus`)

The FMUs in `fmus/x86_64` and `fmus/aarch64` came from PlantCraft Twin (`models/fmus`), built
there from its Modelica package `models/PlantCraftTwin`, original work of the PlantCraft
authors (Apache-2.0), with OpenModelica 1.24.4. They carry, linked in:

| Component | Source | License |
|---|---|---|
| OpenModelica simulation runtime (FMU runtime sources and libraries) | OpenModelica, Open Source Modelica Consortium | OSMC Public License, distributed under its BSD-new option (OSMC-PL 1.8 lets the recipient choose BSD-new, GPL 3 or OSMC-PL) |
| SUNDIALS CVODE (the solver inside the FMUs) | Lawrence Livermore National Laboratory | BSD-3-Clause |
| FMI 2.0 headers | Modelica Association | BSD-2-Clause |

## Data

No third-party dataset is committed. Test loops (`tests/plant.py`) are
synthetic. The simulator oracle's dynamics (`tests/oracles/simulator.py`) are
copied from PlantCraft Simulator (`src/simcraft/loops/dynamics.py`, PlantCraft
authors, Apache-2.0). The International Stiction Database (Jelali and Huang,
2010; published by the editors for teaching and research use, no licence text
given) is fetched by `tests/oracles/fetch_isdb.py` into `oracles/`, never
committed.
