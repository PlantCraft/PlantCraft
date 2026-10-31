# Extreme load C2 B2-LINKCRAFT-2-r1 (2026-10-31T11:06Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 24.423 | ok |
| Analytics checks | 27.48 | ok |
| 9 methods (slowest) | 18.5 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.05 | 0.11 | 0.31 | {'200': 27} |
| person_display_values | 27 | 0.07 | 4.95 | 7.92 | {'200': 26, '429': 1} |
| person_trend_8h | 27 | 0.02 | 3.06 | 3.09 | {'200': 27} |
| method reads | 36 | 16.98 | 18.29 | 18.45 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 37.5 | 5.7 | 0 | 181 |
| compute-gateway | 14.9 | 1.8 | 0 | 52 |
| dashcraft | 42.2 | 3.4 | 0 | 100 |
| doccraft | 23.1 | 2.0 | 0 | 96 |
| histcraft | 128.8 | 54.7 | 17 | 462 |
| histcraft-collector | 30.7 | 4.2 | 0 | 107 |
| histcraft-db | 14.1 | 5.1 | 0 | 129 |
| histcraft-gateway | 0.7 | 0.4 | 0 | 132 |
| installer | 25.3 | 5.9 | 0 | 38 |
| linkcraft | 61.5 | 15.1 | 0 | 397 |
| linkcraft-executor | 224.5 | 28.3 | 9 | 382 |
| llm-egress | 45.8 | 3.5 | 0 | 33 |
| modelcraft | 36.4 | 5.2 | 0 | 166 |
| modelcraft-executor | 5.3 | 0.9 | 0 | 202 |
| processcraft | 53.6 | 13.2 | 0 | 548 |
| proxy | 13.0 | 2.7 | 0 | 29 |
| simcraft | 102.2 | 39.1 | 13 | 336 |
