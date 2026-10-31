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

## A LIMS as a SQL source

A SQL source with **Laboratory results (LIMS)** checked (option `laboratory`) reads laboratory
results, not plant values. Each row is one result at `laboratory:<analysis>`: the time column is
the sampling time, the one tag column names the analysis, and the query gives `value` and, when
the LIMS has them, `status` (`entered`, `approved` or `rejected`) and `received_at` and
`approved_at` as ISO 8601 text with an offset. For example:

```sql
SELECT sampled_at, analysis, result AS value, state AS status,
       to_char(received_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS received_at,
       to_char(approved_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS approved_at
FROM results WHERE updated_at > now() - interval '2 days'
```

The collector writes them as `POST /api/v1/lab` does (`histcraft.lab`): the value at its sampling
time however late it arrives, `uncertain` until approved and `bad` when rejected, and the times
beside it. A row read again unchanged is not written again, so a scan every few minutes over the
last days counts a write only when the LIMS changed the result (a retest, an approval). Late
results are the point here: unlike plant values, they are not dropped for being older than the
newest.

## Store and forward

When the collector does not answer (stopped, upgraded, its database away), the gateway keeps
reading: what it read waits in Telegraf's **disk buffer**, `data/histcraft/gateway-buffer` (the
gateway's `/var/lib/telegraf-buffer`, the only folder it writes), and goes to the collector in
order once it answers again, even when the gateway itself restarted meanwhile. The collector
takes a value only when it is newer than the point's last one, so a batch sent twice (an answer
lost on the way) is taken once and the first value at a time wins.

- Measured with the pinned Telegraf 1.40.2 (`ci/bench/storage/gateway_buffer.md`): collector
  away 15 s, gateway killed and started again, then the collector back: the memory buffer
  delivered 8 of 23 values, the disk buffer all 23, in order, none twice.
  `sources_check/test_gateway.py` repeats it against a Modbus device.
- The cost: Telegraf writes each value through the disk, about 20 times the CPU of the memory
  buffer, and keeps up to about 2,000 values a second (4 vCPU). A gateway that reads more sets
  `HISTCRAFT_GATEWAY_BUFFER=memory` on the collector and accepts losing what waits in memory if
  the gateway restarts during an outage.
- Telegraf marks the disk buffer as experimental and ignores `metric_buffer_limit` with it: the
  buffer grows until the collector takes it. The collector measures it every minute and reports
  `histcraft.gateway.backlog` past 64 MB.
- Telegraf refuses to start on a buffer folder it cannot write. The collector makes the folder
  (0700, Historian's user) and writes a memory buffer instead when it cannot write it.

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
