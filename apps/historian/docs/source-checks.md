# Source checks: every source kind against the Simulator's test kit

> **Decided:** 2026-10-24 by the maintainer (Historian round 7, D1 and D2): no source kind reaches a
> user without a consolidated test; the test servers use the Simulator's plant and stay out of
> the product; public servers are checked by hand only.

`make sources-check` starts each server of the Simulator's test kit (`simcraft.testkit`,
`simulator/src/simcraft/testkit/`), points a Historian source at it as a person would, and
compares what Historian archives or reads with what the kit published. The plant is the same
everywhere: PV, SP, OP and MODE of FIC-101, PIC-102 and LIC-103, 30 minutes on a 10 s grid,
computed again by the check from the same seed.

| Source | Kit server | Cases | Check |
|---|---|---|---|
| CSV files | sample files | wide ISO, wide `+03:00`, wide epoch, Brazilian Excel (`;`, decimal comma, dd/mm local), long with good/bad/uncertain, a file with errors on known lines | every file read as the plant; a CSV source watching `wide-*.csv` archives it; an import of `long.csv` writes values and qualities |
| PI Web API | `testkit.piwebapi` | Basic auth, paging, digital states, 503 bursts, slow answers, wrong password | recorded values and states equal the plant; a burst is retried; a slow server is an error for the tag, not a crash |
| OPC UA | the Simulator itself | live, Browse, Historical Access | values arrive in range, MODE as text, history reads back |
| MQTT | `testkit.mqtt` (amqtt) | number alone, flat JSON, nested JSON, QoS 1, `+` and `#` | through the pinned Telegraf: Browse lists every series, the points added archive the published values |
| Modbus TCP | `testkit.modbus` (pymodbus) | FLOAT32 in 4 byte orders, FLOAT64 and INT64 with 8-byte orders, INT16/UINT16/INT32/UINT32 scaled, input registers, coils, discrete inputs | through Telegraf: every register reads back its value |
| SQL | `testkit.sql` (PostgreSQL) | wide table, long table with a tag column, `timestamp without time zone` | through Telegraf: the archive rebuilds the table's rows |

Gateway kinds run the suite's own Telegraf: the image pinned by digest in `deploy/compose.yaml`,
read from Docker Hub without Docker, every layer checked against its SHA-256
(`sources_check/telegraf.py`; `HISTCRAFT_TELEGRAF` names another binary). SQL needs a
PostgreSQL: `HISTCRAFT_SOURCES_PG`, or `initdb` run by a user other than root; without one SQL
is skipped and the run says so. CI runs the check on every Historian change
(`.github/workflows/historian.yml`, job `sources`, `HISTCRAFT_SOURCES_STRICT=1`: no Telegraf
fails the job).

## What it found (2026-10-24, first run)

- Modbus: Telegraf names the byte order of a 64-bit value by all eight bytes (`ABCDEFGH`,
  `GHEFCDAB`, ...); Historian offered `ABCD`, and Telegraf refused the whole device. Four-letter
  orders saved before are read as their long names.
- Modbus: an integer register with a fractional scale (INT16 x 0.1) came out as an integer,
  552 x 0.1 = 55. It is now sent as Telegraf's fixed point type (FIXED, UFIXED); a one-byte
  type takes a whole-number scale only.
- SQL: Telegraf also sent the time and tag columns as fields, so Browse listed a `time` and a
  `tag` point beside each value. They are excluded.
- OPC UA: history reads took a point's address as a bare identifier in the source's namespace,
  while Browse and the collector use the whole NodeId (`ns=2;s=...`): backfill and mode `both`
  read nothing for points added from Browse. Both forms are read now.
- SQL: rows older than a point's newest value are not archived (the archive only moves forward);
  a table's existing rows are not backfilled when a point is added.

## Public servers, by hand

`make sources-public` runs Historian's readers against public test servers (Eclipse Milo and
node-opcua demos for OPC UA, `test.mosquitto.org` for MQTT) and prints one line per server.
Never in CI: the servers are not ours. Run it at the end of a Historian round and note the
result in `docs/devlog.md`.

## Running it

```
pip install -e "../../simulator[testkit]"    # Python 3.12+
make sources-check                           # HISTCRAFT_SOURCES_PG=postgres://... for SQL
cd ../../simulator && simcraft testkit --serve mqtt,modbus,piwebapi,csv   # by hand
```
