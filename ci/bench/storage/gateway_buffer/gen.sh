#!/bin/sh
# One value a call, a counter: a gap or a repeat shows in what the receiver got.
f="$(dirname "$0")/work/counter"
n=$(cat "$f" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$f"
echo "probe n=${n}i"
