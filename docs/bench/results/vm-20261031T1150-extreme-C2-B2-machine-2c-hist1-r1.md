# Extreme load C2 B2-machine-2c-hist1-r1 (2026-10-31T11:50Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 66 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 35.074 | ok |
| Analytics checks | 41.06 | ok |
| 9 methods (slowest) | 18.3 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 31 | 0.1 | 0.43 | 0.44 | {'200': 31} |
| person_display_values | 31 | 0.11 | 3.94 | 5.1 | {'429': 5, '200': 26} |
| person_trend_8h | 31 | 0.05 | 4.72 | 5.92 | {'200': 30, '502': 1} |
| method reads | 36 | 16.75 | 18.17 | 18.2 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 39.5 | 6.0 | 0 | 223 |
| compute-gateway | 17.3 | 3.5 | 0 | 61 |
| dashcraft | 0.3 | 0.2 | 0 | 97 |
| doccraft | 33.9 | 2.5 | 0 | 86 |
| histcraft | 107.5 | 31.5 | 13 | 568 |
| histcraft-collector | 102.3 | 11.0 | 4 | 140 |
| histcraft-db | 8.5 | 2.7 | 0 | 96 |
| histcraft-gateway | 2.9 | 0.5 | 0 | 130 |
| installer | 36.2 | 4.5 | 0 | 32 |
| linkcraft | 64.4 | 11.6 | 0 | 592 |
| linkcraft-executor | 79.1 | 15.3 | 0 | 337 |
| llm-egress | 45.8 | 4.4 | 0 | 29 |
| modelcraft | 0.5 | 0.3 | 0 | 164 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 195 |
| processcraft | 73.7 | 16.6 | 0 | 585 |
| proxy | 20.4 | 2.6 | 0 | 31 |
| simcraft | 84.4 | 24.7 | 0 | 338 |
