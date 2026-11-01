#!/bin/sh
# What the disk buffer costs: 20 s of RATE values a second (gen2.sh) into Historian's ingest app.
# Usage: throughput.sh disk|memory [RATE]   (TELEGRAF=<binary>)
set -u
DIR=$(cd "$(dirname "$0")" && pwd); MODE=${1:-disk}; RATE=${2:-2000}
T=${TELEGRAF:-$(cd "$DIR/../../../../apps/historian" && python -c "from sources_check.telegraf import binary; print(binary())")}
rm -rf "$DIR/work"; mkdir -p "$DIR/work/buf"; cd "$DIR/work"
B=""; [ "$MODE" = disk ] && B="buffer_strategy = \"disk\"
  buffer_directory = \"$DIR/work/buf\""
cat > tp.conf <<EOC
[agent]
  interval = "1s"
  flush_interval = "1s"
  metric_batch_size = 5000
  metric_buffer_limit = 1000000
  $B
  omit_hostname = true
[[outputs.influxdb_v2]]
  urls = ["http://127.0.0.1:18086"]
  token = "x"
  organization = "o"
  bucket = "b"
[[inputs.exec]]
  commands = ["$DIR/gen2.sh $RATE"]
  data_format = "influx"
  timeout = "5s"
EOC
python3 "$DIR/recv.py" 18086 got.txt & R=$!; sleep 1
"$T" --config tp.conf > tgp.log 2>&1 & P=$!; sleep 20
TICKS=$(awk '{print $14+$15}' /proc/$P/stat)
kill $P; sleep 2; kill $R
echo "$MODE at $RATE/s: received $(wc -l < got.txt) of $((RATE * 20)) in 20 s, Telegraf CPU $TICKS/100 s"
