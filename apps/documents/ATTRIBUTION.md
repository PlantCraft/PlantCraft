# Third-party assets and libraries

Every third-party asset (font, icon, image, dataset) and every direct dependency
has a row here (AGENTS.md, "Clean room"). The PlantCraft Documents mark (`docs/images/logo.svg`,
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
| NumPy (vectors and exact search), pandas (through plantcraft-sdk) | BSD-3-Clause |
| pypdf | BSD-3-Clause |
| python-docx, python-pptx | MIT |
| openpyxl | MIT |
| lxml (through python-docx, python-pptx) | BSD-3-Clause |
| Pillow (through python-pptx) | MIT-CMU |
| onnxruntime | MIT |
| tokenizers (Hugging Face) | Apache-2.0 |
| pydantic | MIT |
| httpx | BSD-3-Clause |
| cryptography (through plantcraft-sdk) | Apache-2.0 or BSD-3-Clause |
| FastAPI, Starlette, Uvicorn | MIT / BSD-3-Clause |
| pytest, Ruff (development only) | MIT |
| Playwright for Python (e2e tests only, never in the image) | Apache-2.0 |

## Model (bundled in the image, downloaded at build only)

| Model | Source | License |
|---|---|---|
| multilingual-e5-small | `intfloat/multilingual-e5-small` (Wang et al., 2024); ONNX export with 8-bit weights by `Xenova/multilingual-e5-small` | MIT |

## Data

One third-party drawing is committed, for the plant-map reader's tests:
`tests/files/dexpi-C01V01-HEX.EX02.pdf`, the example P&ID "C01V01-HEX.EX02" of the DEXPI
Training Test Cases (DEXPI initiative, https://gitlab.com/dexpi/TrainingTestCases), licensed
CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/); unchanged. No other third-party dataset
is committed. `tests/files/incident.pdf` is one of the suite's invented
demo documents (PlantCraft `deploy/demo/documents/`). The test plant (`plantcraft_sdk.testplant`, a port of
The Simulator's loop equations) is synthetic.
