# The gateway's buffer: memory or disk (store and forward, H3)

31/10/2026, Telegraf 1.40.2 (the image `deploy/compose.yaml` pins), 4 vCPU cloud VM, into
Historian's own ingest app (`histcraft.collector.ingest`). Scripts in `gateway_buffer/`.

## Outage (`outage.sh disk|memory`)

The collector is away 15 s while the gateway reads one value a second; the gateway is killed
(`kill -9`) and started again; the collector comes back.

| Buffer | Read | Received | Distinct | Order |
|---|---|---|---|---|
| memory (before) | 23 | 8 | 8 | in order, the 15 read while away lost |
| disk | 23 | 23 | 23 | in order, none twice |

The same against a Modbus device: `apps/historian/sources_check/test_gateway.py`
(`test_values_read_while_the_collector_is_away_arrive_after_a_gateway_restart`); with the
memory buffer it gets only the 4 seconds after the restart.

## Cost (`throughput.sh disk|memory RATE`, 20 s)

| Buffer | Rate offered | Received | Telegraf CPU |
|---|---|---|---|
| memory | 2,000/s | 40,000 of 40,000 | 0.3 s |
| disk | 2,000/s | 40,000 of 40,000 | 7.0 s |
| disk | 5,000/s | 50,000 of 100,000 | 8.4 s |
| memory | 20,000/s | 400,000 of 400,000 | 1.1 s |
| disk | 20,000/s | 67,559 of 400,000 | 11.8 s |

The disk buffer writes every value through the disk: about 20 times the CPU, and it keeps up
to about 2,000 to 3,000 values a second. Telegraf ignores `metric_buffer_limit` with it (a
limit of 5 still delivered all 23) and marks it experimental; it refuses to start on a folder
it cannot write. Hence: disk by default, made and checked by the collector, memory when the
folder is not writable or with `HISTCRAFT_GATEWAY_BUFFER=memory`, and the condition
`gateway.backlog` past 64 MB.
