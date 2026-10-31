# PlantCraft Historian spec

Category: the process historian, what the historians of process plants offer: collect values from
control systems on a scan or by exception, compress them, keep years of history in little space,
and serve recorded, interpolated and aggregated values to people and other tools. Tools studied
(research only, public behaviour): commercial process historians and the historian layers of
SCADA and IIoT platforms. Sources are public only (clean room, see AGENTS.md).

## Sources

| Source | Link | Read on |
|---|---|---|
| E. H. Bristol, "Swinging door trending: adaptive trend recording?", ISA National Conference, 1990 | (paper; the algorithm is also described in the public literature below) | 2026-10-19 |
| OPC UA Part 4, Services (Read, Browse) | https://reference.opcfoundation.org/Core/Part4/ | 2026-10-19 |
| OPC UA Part 8, Data Access (EURange, EngineeringUnits) | https://reference.opcfoundation.org/Core/Part8/ | 2026-10-19 |
| OPC UA Part 11, Historical Access | https://reference.opcfoundation.org/Core/Part11/ | 2026-10-19 |
| OPC UA Part 13, Aggregates (time-weighted average, interpolation) | https://reference.opcfoundation.org/Core/Part13/ | 2026-10-19 |
| PI Web API reference (public): recorded, interpolated, summary | https://docs.aveva.com/bundle/pi-web-api-reference/ | 2026-10-19 |

## Features

| Area | Feature in the target tools | Source | Ours | Test or oracle |
|---|---|---|---|---|
| Collection | Scan-based collection from OPC UA servers | Part 4 | done | `tests/test_collector.py` |
| Collection | Read history from PI Web API (recorded values, paging, digital states), GET only | PI Web API reference | done | `tests/test_source_history.py` |
| Collection | Read history from OPC UA Historical Access servers (HistoryRead raw) | Part 11 | done | `tests/test_source_history.py` |
| Collection | Read history from CSV files in place | | done | `tests/test_source_history.py`, `tests/test_api.py` |
| Collection | Per signal: read from the source, archive here, or both | | done (archive for OPC UA only, G15) | `tests/test_api.py` |
| Archive | Series computed by apps stored as derived signals, with subject and result | app standard | done | `tests/test_api.py` |
| Collection | Browse a server and pick points, with units and ranges | Part 4, Part 8 | done | `tests/test_collector.py` |
| Collection | Subscriptions (report by exception from the server) | Part 4 | missing (polling only) | |
| Collection | Bad quality and lost connections recorded, never bridged | | done | `tests/test_collector.py`, `tests/test_compression.py` |
| Collection | Store and forward when the archive is unreachable (edge buffering) | | missing | |
| Collection | Other protocols through the gateway (Telegraf): MQTT, Modbus TCP, SQL | | done (Sparkplug B and OPC DA still missing) | `tests/test_gateway.py` |
| Collection | Secure OPC UA (Sign, SignAndEncrypt, certificates) | Part 4 | done (client certificate made once; server trusted by SHA-256) | `tests/test_secure_opcua.py` |
| Compression | Swinging-door compression with a deviation per point | Bristol 1990 | done | `tests/test_compression.py` |
| Compression | Maximum time between archived values | | done | `tests/test_compression.py` |
| Compression | Minimum time between archived values (per point, lines only; PI CompMin) | | done | `tests/test_compression.py`, `tests/test_settings_levels.py` |
| Compression | Step marker: a held value that jumps is archived at its last read before the jump | | done (the swinging door's held snapshot) | `tests/test_compression.py` |
| Compression | Exception deviation before compression (two-stage filter) | | done (exception 0.1 % and compression 0.2 % of the span by default, like PI; named profiles `fine` and `none`) | `tests/test_compression.py` |
| Compression | Step points and text (digital states) archived on change | | done | `tests/test_compression.py` |
| Archive | Compressed storage, merged over time | | done | `tests/test_archive.py`, bench |
| Archive | Retention per point | | done (whole chunks; PostgreSQL drops whole past months) | `tests/test_archive.py`, `tests/test_partitions.py` |
| Archive | PostgreSQL tables partitioned by month, an older archive migrated on start | | done | `tests/test_partitions.py` |
| Admin | Settings in three levels (general, per source, per point; the most specific wins), with the origin of each value shown | | done | `tests/test_settings_levels.py` |
| Archive | Notes on a signal at an instant or over an interval, told to PlantCraft as events | | done (`/api/v1/annotations`, the signal's page; the page posts `histcraft.annotation.added`) | `tests/test_annotations.py` |
| Archive | The OPC UA status code kept with each change of quality: sub-code (`UncertainLastUsableValue`...) and LimitBits (low, high, constant) | Part 4 §7.39 | done (`status` and `limit` beside `quality` in reads) | `tests/test_quality.py` |
| Archive | Quality flags stored with values (good, uncertain, substituted, bad) | Part 11 | done (changes of quality kept per point; sources without quality count as good) | `tests/test_quality.py` |
| Archive | Backfill from the source's own history (OPC UA HistoryRead), up to where archiving began | Part 11 | done | `tests/test_backfill.py` |
| Archive | Edits of archived values with an audit trail | Part 11 | missing | |
| Archive | Backup of a live archive | | partial (the suite's install.sh backs up the data folder) | |
| Reads | Recorded values in a range | Part 11 | done | `tests/test_query.py` |
| Reads | Time-weighted averages on a regular grid | Part 13 | done | `tests/test_query.py` |
| Reads | Interpolated values at given times | Part 13 | partial (inside the aggregates, no route) | |
| Reads | Aggregates: min, max, mean, std, last over a window | Part 13 | done | `tests/test_query.py` |
| Reads | Served to the suite in PlantCraft API v1 shapes | | done (PlantCraft side pending) | `tests/test_api.py` |
| Reads | OPC UA Historical Access server for third-party tools | Part 11 | missing | |
| Admin | Pages: sources, browse, points, status, trend, settings, help, in the suite frame (`@plantcraft/ui`) | | done | screenshots in `docs/devlog.md` |
| Admin | Bulk point import and export (CSV) | | done (preview, then apply) | `tests/test_points_csv.py` |
| Admin | Calculated and totalized points | | done (formulas over archived points, totalizer with reset) | `tests/test_calc.py` |
| Platform | Works offline, on premises, isolated network | | done | `tests/test_suite_rules.py` |
| Platform | Read-only toward plant systems | | done | `tests/test_read_only.py` |
