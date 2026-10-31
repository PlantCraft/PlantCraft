# Extreme load C2 hunt-cache0-r1 (2026-10-31T14:00Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 63 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 38.828 | ok |
| Analytics checks | 25.93 | ok |
| 9 methods (slowest) | 30.9 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 33 | 0.08 | 0.26 | 0.4 | {'200': 33} |
| person_display_values | 33 | 0.11 | 3.14 | 3.69 | {'200': 33} |
| person_trend_8h | 33 | 0.04 | 1.98 | 2.1 | {'200': 33} |
| method reads | 36 | 21.79 | 30.42 | 30.79 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 56.4 | 11.6 | 0 | 227 |
| compute-gateway | 23.3 | 4.5 | 0 | 52 |
| dashcraft | 36.9 | 3.4 | 0 | 100 |
| doccraft | 23.3 | 3.2 | 0 | 99 |
| histcraft | 196.7 | 77.2 | 26 | 776 |
| histcraft-collector | 75.8 | 8.8 | 0 | 118 |
| histcraft-db | 25.2 | 4.1 | 0 | 141 |
| histcraft-gateway | 0.7 | 0.4 | 0 | 32 |
| installer | 25.2 | 6.3 | 0 | 38 |
| linkcraft | 44.3 | 15.1 | 0 | 644 |
| linkcraft-executor | 187.5 | 30.9 | 9 | 387 |
| llm-egress | 40.0 | 4.3 | 0 | 30 |
| modelcraft | 32.7 | 4.0 | 0 | 149 |
| modelcraft-executor | 0.8 | 0.6 | 0 | 9 |
| processcraft | 51.7 | 15.9 | 0 | 566 |
| proxy | 13.7 | 2.9 | 0 | 19 |
| simcraft | 81.7 | 31.1 | 0 | 320 |
