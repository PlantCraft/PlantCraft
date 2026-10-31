#!/bin/sh
# Store and forward with the pinned Telegraf: the receiver (Historian's ingest app) is away 15 s,
# the gateway is killed in the meantime and started again, then the receiver comes back.
# Usage: outage.sh disk|memory   (TELEGRAF=<binary>, default: sources_check's cached one)
set -u
DIR=$(cd "$(dirname "$0")" && pwd); MODE=${1:-disk}
T=${TELEGRAF:-$(cd "$DIR/../../../../apps/historian" && python -c "from sources_check.telegraf import binary; print(binary())")}
rm -rf "$DIR/work"; mkdir -p "$DIR/work/buf"; cd "$DIR/work"
sed "s#@DIR@#$DIR/work#g; s#@GEN@#$DIR/gen.sh#g" "$DIR/outage.conf.in" > t.conf
[ "$MODE" = memory ] && sed -i '/buffer_strategy\|buffer_directory/d' t.conf
"$T" --config t.conf > tg1.log 2>&1 & P=$!; sleep 15; kill -9 $P; sleep 1
echo "read while away: $(cat counter)"
python3 "$DIR/recv.py" 18086 got.txt & R=$!; sleep 1
"$T" --config t.conf > tg2.log 2>&1 & P=$!; sleep 8; kill $P; sleep 2; kill $R
echo "$MODE: read $(cat counter), received $(grep -c probe got.txt), distinct $(grep -o 'n=[0-9]*' got.txt | sort -u | wc -l)"
