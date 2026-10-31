# Extreme load C2 B2-DASHCRAFT-2-r1 (2026-10-31T11:20Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 25.811 | ok |
| Analytics checks | 29.79 | ok |
| 9 methods (slowest) | 19.6 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.05 | 0.12 | 0.13 | {'200': 27} |
| person_display_values | 27 | 0.07 | 3.44 | 6.74 | {'200': 26, '429': 1} |
| person_trend_8h | 27 | 0.03 | 3.97 | 4.51 | {'200': 27} |
| method reads | 36 | 18.37 | 19.56 | 19.59 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 42.8 | 8.3 | 0 | 181 |
| compute-gateway | 13.1 | 1.5 | 0 | 51 |
| dashcraft | 47.7 | 6.9 | 0 | 106 |
| doccraft | 34.3 | 2.8 | 0 | 84 |
| histcraft | 128.6 | 49.5 | 17 | 453 |
| histcraft-collector | 2.7 | 1.6 | 0 | 97 |
| histcraft-db | 18.2 | 3.6 | 0 | 100 |
| histcraft-gateway | 0.5 | 0.4 | 0 | 136 |
| installer | 28.7 | 6.3 | 0 | 32 |
| linkcraft | 83.6 | 11.9 | 0 | 566 |
| linkcraft-executor | 113.1 | 12.7 | 4 | 393 |
| llm-egress | 34.8 | 3.4 | 0 | 32 |
| modelcraft | 11.9 | 1.2 | 0 | 168 |
| modelcraft-executor | 6.4 | 1.3 | 0 | 201 |
| processcraft | 43.8 | 8.4 | 0 | 569 |
| proxy | 8.6 | 2.0 | 0 | 30 |
| simcraft | 88.4 | 30.0 | 0 | 287 |
