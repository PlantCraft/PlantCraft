# Configuration file

The **configuration file** (the plant map) sets an installation up at once:
its data sources, the signals in use, the asset tree and the loops, in one
Excel or JSON file. Use it to start a plant or to copy one installation to
another. Day-to-day work on sources and signals (browsing tags, choosing what
to keep, their history) happens in the **Historian** app; the asset tree alone
moves with **Assets › Import** and **Export**.

> Since 2026-10-24 the configuration file has no page in PlantCraft (the owner
> found it unclear next to the asset import, and an upload over a plant in use
> was risky). It stays for scripted setups and for copying one installation to
> another, through the API with an administrator's session:
> `GET /api/map/template.xlsx` or `/api/map/export.json`, then
> `POST /api/map/preview?filename=<file>` and `POST /api/map/apply?filename=<file>`
> with the file as the body (`ci/bench/suite_bench.py` does exactly this). In the
> interface, the asset tree is imported in **Assets › Import**, and the last
> import can be undone there; sources and signals belong to the Historian.

## The file

The file has four lists: download the template, or export the current
configuration, fill it in, preview it and apply it.

- **Excel (.xlsx)**: one sheet per list, with the column names in the first
  row. The template's read-me sheet explains each column. Sheets with
  Portuguese names (`fontes`, `ativos`, `sinais`, `malhas`) are also accepted.
- **JSON**: an object with the lists `sources`, `assets`, `signals` and `loops`.
- **CSV**: a single list, with the sheet name as the file name (`signals.csv`,
  `assets.csv`...).

### `sources`

| Column | Required | What it is |
| --- | --- | --- |
| `source_id` | yes | Identifier used in the `signals` sheet. `scenario` is the scenario source (read-only). |
| `name` | yes | Name shown on the platform. |
| `type` | yes | `opcua`, `pi_web_api` or `csv`. |
| `endpoint_url`, `namespace_uri` | OPC UA | Server address and namespace of the NodeIds. |
| `base_url`, `server` | PI | PI Web API address and PI Data Archive name. |
| `path` | CSV | Path of the file on the server. |
| `auth_type` | | OPC UA: `anonymous` or `basic`. PI: `kerberos`, `ntlm` or `basic`. |
| `username`, `password_env` | | Username and the environment variable holding the password. Never write the password in the file. |
| `timeout_seconds` | | Maximum time for each read. |
| `tags` | PI | The source's tags separated by `;`. |

### `assets`

| Column | Required | What it is |
| --- | --- | --- |
| `asset_id` | yes | Identifier without spaces (`U-200`, `B-201A`). |
| `name` | yes | Name shown in the tree. |
| `kind` | yes | Asset type: `unit`, `area`, `equipment`, `loop` or another type registered on the platform. |
| `parent_id` | | Parent asset; empty: directly under the installation. |
| `description` | | Free description. |
| `attributes` | | Asset attributes: in JSON, an object (`{"power_kw": 75}`); in the workbook, each extra column of the sheet. They are not stored yet: the preview warns which were ignored. |

### `signals`

| Column | Required | What it is |
| --- | --- | --- |
| `tag` | yes | The tag in the source (string NodeId in OPC UA, point in PI, column in CSV). |
| `source_id` | | The tag's source; empty: the scenario source. |
| `name`, `unit` | | Readable name and engineering unit. |
| `asset_id` | | Asset the signal belongs to. A tag can appear in several rows, one per asset. |
| `role` | | The signal's role in the asset (`pv`, `pressure`, `vibration`...). |
| `monitor` | | `yes`/`no`: the platform follows the signal. Empty: yes. |

### `loops` (control loops)

| Column | Required | What it is |
| --- | --- | --- |
| `loop_id` | yes | Loop tag (`FIC-2001`); also the id of the loop's asset. |
| `name` | yes | Loop name. |
| `asset_id` | | Asset where the loop sits in the tree (the equipment). Empty: under the unit and area. |
| `area`, `unit`, `service` | | Area (groups in the panels), process unit and short description. |
| `pv` | yes | Process variable tag. |
| `sp`, `op`, `mode`, `secondary` | | Tags of the setpoint, output, mode and a secondary variable. |
Each loop becomes an asset of kind `loop` with its signals by role, so every
app of the suite finds it: Analytics analyses it in its next round. How a loop
is analysed (`protocol`, `loop_type`, `criticality`, `enabled`) is set in
Analytics; those columns, when present, are ignored here with a warning. A loop
that comes from the scenario file is changed in that file, not by the map.

### Preview, apply and re-import

The preview counts, per sheet, what will be created, changed or stay the same,
and lists the problems with sheet and row (in the workbook, row 2 is the first
after the header):

- **Errors** block the import: required column empty, invalid asset or source
  type, source or asset that does not exist, a loop without `pv`, the same tag
  with two sources.
- **Warnings** do not block: tag that does not exist in the source, unknown
  parent asset (the asset goes under the installation), password still to be
  typed, ignored attributes and loop settings.

**Apply** (admins only) writes everything at once. Importing the same file
again changes nothing. What is not in the file stays as it is; only with the
**Remove what is not in the file** option does the platform remove the added
sources, hand-made assets, signal links and loops from a map that the file
does not list (scenario loops are never removed).

To edit in Excel: **Export current map (Excel)**, edit and import it back.
Without edits, the preview says nothing changes.

## Building the map from the manuals with a language model

The shortest path for a new plant is usually: gather the manuals and I/O lists
of the equipment, ask your AI assistant to build the JSON and check the result
in the preview before applying. For the asset tree, **Assets › Import › Copy as
prompt** puts a ready prompt on the clipboard: the file's format, an example,
this installation's asset types and the rules the answer must follow. For a
whole map, the same kind of prompt comes from the API (`/api/prompts/plant-map`).

The button only fills the clipboard: nothing is sent anywhere. The prompt never
carries a data source's address, user name or password; sources are set up in
Settings, and the assistant is asked only for assets, signals, loops and relations.

Then preview the JSON (Assets › Import, or `/api/map/preview`) and read it carefully:
warnings about tags that do not exist in the source are usually reading
mistakes by the model.

## For whoever deploys

- Added sources live in the `data_sources` table of the database; the signals
  in use and the source of each tag, in `signal_routes`. The key that encrypts
  the passwords is in `sources.key` next to the database (or in the file named
  by `PLANTCRAFT_SOURCES_KEY_FILE`). Without the key, stored passwords must
  be typed again.
- Each data read goes to the source that owns each tag; tags without an owner
  are read from the scenario source, exactly as before. Added OPC UA and PI
  sources use the same local history cache as the scenario source.
- Reading and writing Excel workbooks uses the `openpyxl` package (the
  `server` dependency group).
