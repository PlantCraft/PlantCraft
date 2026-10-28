# Your data: where it lives and how to take it out

For a plant that wants to know, before it starts, that it can leave. PlantCraft keeps every
piece of a plant's data on the plant's own server, in open formats, and gives each kind of data a
way out. No licence, account or call home is needed to read it, and the code that reads it is
open (Apache License 2.0).

## Where it lives

All of an installation's state is in one folder, `data/` of the install folder
([install-offline.md](install-offline.md), section 10): one subfolder per app, SQLite databases,
the Historian's PostgreSQL database and plain files. `backups/` holds one folder per backup
(every night at 02:00, before every update, and by hand with `./install.sh --backup`). Removing
the suite with `./install.sh --uninstall` stops it and keeps the data and the backups; only
`--purge` deletes them.

The plant's own systems keep their data too: PlantCraft only reads OPC UA, PI Web API, MQTT,
Modbus TCP, SQL and CSV sources, so a historian you already have stays the reference.

## How each kind of data comes out

| Data | Format | Where |
|---|---|---|
| Process values (the history) | CSV in a ZIP: `series.csv` (time in UTC, one column per tag), `signals.csv`, `assets.csv`, `plant-map.json` | Historian › **Exports**: pick tags, loops or units and a period; names can be replaced by aliases for a consultant |
| Process values, by program | JSON (time and value arrays) | API v1, `GET /api/v1/signals/{id}/series`, or a notebook ([notebooks](en/notebooks.md)) |
| A trend | CSV | View › Trends › download its data |
| The asset tree | JSON, Excel, CSV, B2MML or AF XML | PlantCraft, assets: export (`/api/asset-file/export.<format>`) |
| The plant map (sources, signals, assets, loops) | JSON or Excel, the same file you import | PlantCraft, plant map: export ([configuration file](en/configuration-file.md)) |
| Historian points | CSV | Historian, points: export |
| Process models | Modelica files in a ZIP, laid out as a Modelica library; FMU (FMI 2.0 and 3.0) | Models › project › export; Models › FMU export |
| Model studies and runs | ZIP of the study with its runs; each run's results as CSV | Models › study › export; run › results.csv |
| Reports | PDF, Word (.docx), HTML, Markdown | View › Reports |
| Who did what | CSV | PlantCraft › Audit log › Download CSV |
| Analytics' methods and blocks | Python source, open | `apps/link/` in the repository; algorithms are JSON diagrams of those blocks |

Notebooks read signals, series, assets and the results the apps publish through API v1, with
the permissions of the person who runs them, so whatever they read can be written to a file
from Python.

## Leaving

1. Export what you want to keep in the formats above, or keep a copy of `data/` and `backups/`:
   SQLite and PostgreSQL read anywhere.
2. `./install.sh --uninstall --purge` removes the containers, the images, the data and the
   backups from the server ([install.md](install.md), Remove it).

Nothing else to cancel: there is no account, licence key or subscription in the software.
