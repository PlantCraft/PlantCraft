# Time-series database bench (2026-10-31 plan, items A1.4 and A4)

Test code only: nothing here runs in the product. It answers one question: would another
time-series database make the Historian's reads (above all Analytics' rounds) ten times faster?

- `dataset.py`: A1.4, the standard dataset shared by every read bench of the plan. 2,000 points x 1
  year of archived values made with the Historian's real Compressor, built one day at a time and
  identical on every machine.
- `engines.py`: one adapter per database, each in its own Docker container with the same CPU and
  memory limits: today's Historian (PostgreSQL 17 + compressed chunks, read by the real
  `ArchiveStore`), TimescaleDB, ClickHouse, QuestDB, InfluxDB 3 Core, TDengine, VictoriaMetrics, and
  DuckDB over Parquet files.
- `bench.py`: loads N days and runs the same reads on each (trend, Analytics round of 200 signals x
  24 h, fleet of 2,000 x 24 h, 60 s grid, long trend, incremental 15 min, last value, and the round
  with 1 to 16 clients at once). Every read ends in numpy arrays in Python, the time includes that.

```bash
dockerd &                                   # if no daemon runs
pip install numpy pandas pyarrow duckdb "psycopg[binary]" psycopg_pool zstandard \
    clickhouse-connect influxdb3-python questdb taos-ws-py orjson psutil
python ci/bench/tsdb/bench.py all --engine clickhouse --days 7     # load, check, query, conc
python ci/bench/tsdb/bench.py stop --engine clickhouse
```

Environment: `TSDB_CPUS` / `TSDB_MEMORY` (container limits, default 4 / 4g), `TSDB_DATA`,
`TSDB_VOL`, `TSDB_OUT` (results, JSON lines), `TSDB_MACHINE` (label in the results).
