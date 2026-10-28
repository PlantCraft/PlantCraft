# The gateway: MQTT, Modbus TCP and SQL through Telegraf

> **Decided:** 2026-10-23 by the maintainer (Historian round 6): use Telegraf for further source
> types instead of writing connectors, copying its formats as far as possible.

Historian reads OPC UA, PI Web API and CSV itself. Other plant systems are read by
[Telegraf](https://github.com/influxdata/telegraf) (MIT), run unchanged as the
`histcraft-gateway` service, which pushes every value to the collector:

```
MQTT broker / Modbus device / SQL database
        |  inputs.mqtt_consumer, inputs.modbus, inputs.sql (read only)
        v
histcraft-gateway (Telegraf)  --  POST /api/v2/write, InfluxDB line protocol, token  -->
histcraft-collector :HISTCRAFT_INGEST_PORT  -->  compression, archive, snapshots
```

## Who writes what

- The **collector** writes the gateway's whole configuration, `<data>/gateway/telegraf.conf`
  (0600), from the enabled sources of kind `mqtt`, `modbus` and `sql`, whenever one changes.
  Telegraf reloads it (`--watch-config poll`). Nothing else configures the gateway.
- Each input carries the tag `histcraft_source = "<source id>"`; `inputs.internal` (tag
  `gateway`) is the gateway's heartbeat. The one output is `outputs.influxdb_v2` to the
  collector, with the token in `<data>/gateway/token` (made by the collector on first start).
- Every value in the file is a TOML basic string written by `json.dumps`: a topic, a query or
  a password cannot add a line, a table or another plugin.

## Read only

- MQTT subscribes; Modbus reads holding and input registers, coils and discrete inputs; SQL
  runs the source's one SELECT (refused when it holds a write keyword, `INTO` or a second
  statement). Give SQL sources a database user that can only read.
- `tests/test_read_only.py` checks the configuration names only those inputs and one output.

## Addresses and points

A point's address is the metric's series key and field, as line protocol writes them, tags
sorted and without `histcraft_source`: `modbus,name=plc,slave_id=3,type=holding_register FT-101`.
Browse lists every series the gateway sent (up to 20,000 per source) with a suggested tag:
the topic with dots for MQTT, the register name for Modbus, the tag columns and the column for
SQL. Values older than the point's newest are dropped (the archive only moves forward).

## Liveness

A gateway source is connected while values arrive; after 60 s (or three of its scan periods)
without one it is disconnected and its points get a gap, as an OPC UA outage does. The
gateway reads every scan period of the source (10 s when the source sets none); MQTT is pushed
as messages arrive.

## Formats compared

| | Telegraf (line protocol) | Historian |
|---|---|---|
| Identity | measurement + tags + field | source + tag, address = series key + field |
| Value | float, int, uint, bool, string | number (bool and ints as numbers) or text |
| Time | ns since 1970, per metric | ms since 1970, per value |
| Quality | none (an OPC UA input adds a `Quality` tag) | good, uncertain, substituted, bad per change |
| Storage | the output's | swinging door, zstd chunks, monthly partitions (PostgreSQL) |

Telegraf's own `outputs.postgresql` is not used: it would store every value uncompressed and
outside Historian's archive. The archive's database can change later without touching the
gateway: it only speaks line protocol to the collector.
