# Extreme load C2 B2-HISTCRAFT-4-r1 (2026-10-31T11:17Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 25.875 | ok |
| Analytics checks | 27.92 | ok |
| 9 methods (slowest) | 18.9 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.06 | 0.09 | 0.1 | {'200': 27} |
| person_display_values | 27 | 0.07 | 4.08 | 4.56 | {'429': 1, '200': 26} |
| person_trend_8h | 27 | 0.02 | 4.96 | 5.15 | {'200': 27} |
| method reads | 36 | 16.5 | 18.18 | 18.84 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 42.0 | 6.5 | 0 | 186 |
| compute-gateway | 12.1 | 1.8 | 0 | 53 |
| dashcraft | 33.9 | 2.9 | 0 | 98 |
| doccraft | 33.0 | 2.8 | 0 | 83 |
| histcraft | 121.0 | 49.6 | 17 | 433 |
| histcraft-collector | 115.8 | 18.3 | 4 | 139 |
| histcraft-db | 13.3 | 3.5 | 0 | 91 |
| histcraft-gateway | 0.6 | 0.4 | 0 | 136 |
| installer | 16.3 | 3.9 | 0 | 25 |
| linkcraft | 113.7 | 14.1 | 4 | 574 |
| linkcraft-executor | 249.8 | 24.0 | 4 | 370 |
| llm-egress | 0.0 | 0.0 | 0 | 17 |
| modelcraft | 31.4 | 4.9 | 0 | 180 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 201 |
| processcraft | 54.0 | 11.6 | 0 | 564 |
| proxy | 11.7 | 1.7 | 0 | 29 |
| simcraft | 93.1 | 28.4 | 0 | 285 |
