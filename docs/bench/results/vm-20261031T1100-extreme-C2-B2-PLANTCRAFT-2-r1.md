# Extreme load C2 B2-PLANTCRAFT-2-r1 (2026-10-31T11:00Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 51 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 20.313 | ok |
| Analytics checks | 23.16 | ok |
| 9 methods (slowest) | 15.9 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.05 | 0.08 | 0.12 | {'200': 27} |
| person_display_values | 27 | 0.06 | 4.32 | 5.62 | {'200': 26, '429': 1} |
| person_trend_8h | 27 | 0.02 | 2.51 | 3.19 | {'200': 27} |
| method reads | 36 | 13.36 | 15.59 | 15.88 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 43.8 | 9.3 | 0 | 179 |
| compute-gateway | 11.0 | 1.8 | 0 | 52 |
| dashcraft | 34.6 | 3.1 | 0 | 98 |
| doccraft | 7.1 | 0.8 | 0 | 93 |
| histcraft | 117.4 | 45.2 | 13 | 392 |
| histcraft-collector | 3.8 | 2.0 | 0 | 94 |
| histcraft-db | 20.6 | 4.6 | 0 | 98 |
| histcraft-gateway | 0.6 | 0.4 | 0 | 132 |
| installer | 32.1 | 5.1 | 0 | 35 |
| linkcraft | 112.2 | 16.7 | 4 | 532 |
| linkcraft-executor | 159.6 | 17.4 | 4 | 370 |
| llm-egress | 41.0 | 3.4 | 0 | 18 |
| modelcraft | 44.5 | 5.8 | 0 | 146 |
| modelcraft-executor | 0.7 | 0.5 | 0 | 203 |
| processcraft | 36.7 | 10.0 | 0 | 318 |
| proxy | 10.2 | 1.8 | 0 | 29 |
| simcraft | 25.3 | 19.5 | 0 | 299 |
