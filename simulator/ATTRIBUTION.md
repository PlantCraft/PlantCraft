# Third-party assets and libraries

Every third-party asset (font, icon, image, dataset) and every direct dependency has a row here
(AGENTS.md, "Clean room"). The PlantCraft Simulator mark (`docs/images/logo.svg`, copied from
PlantCraft's `docs/images/apps/simcraft.svg`) is original work of the PlantCraft authors
(Apache-2.0).

## Python libraries

| Library | Use | License |
|---|---|---|
| asyncua (FreeOpcUa) | OPC UA server, client and SQLite historian | LGPL-3.0-or-later, used as an unmodified dependency, never copied |
| aiosqlite, aiofiles, cryptography, pyOpenSSL, python-dateutil, pytz, sortedcontainers, typing-extensions (through asyncua) | asyncua's own dependencies | MIT / Apache-2.0 / BSD |
| pytest, pytest-cov, jsonschema, build, Ruff (development only) | tests, schema checks, packaging, lint | MIT / Apache-2.0 |
| amqtt (source test kit only, extra `testkit`) | the MQTT broker of `simcraft.testkit` | MIT |
| pymodbus (source test kit only, extra `testkit`) | the Modbus TCP device of `simcraft.testkit` | BSD-3-Clause |
| psycopg (source test kit only, extra `testkit`) | writes the kit's tables into a PostgreSQL | LGPL-3.0-only, used as an unmodified dependency |

## Data

No third-party dataset is committed. The benchmark catalog (`src/simcraft/catalog/*.csv`) and
the 50-loop portfolio (`src/simcraft/loops/dynamics.py`) are synthetic and original to this
repository. The published works that motivate the benchmark design are cited in `README.md`
and `SPEC.md`; no code, process data or model implementation from them is included.
