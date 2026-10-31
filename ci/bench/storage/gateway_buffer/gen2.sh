#!/bin/sh
# $1 values in one call, each its own series and time.
python3 -c "
import sys, time
t = time.time_ns()
print('\n'.join(f'probe,s=a{i % 500} n={i}i {t + i}' for i in range(int(sys.argv[1]))))" "${1:-2000}"
