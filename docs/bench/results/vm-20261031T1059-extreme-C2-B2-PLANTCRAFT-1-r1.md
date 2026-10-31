# Extreme load C2 B2-PLANTCRAFT-1-r1 (2026-10-31T10:59Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 51 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 20.617 | ok |
| Analytics checks | 23.39 | ok |
| 9 methods (slowest) | 14.8 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.06 | 0.09 | 0.15 | {'200': 27} |
| person_display_values | 27 | 0.07 | 3.54 | 5.42 | {'200': 26, '429': 1} |
| person_trend_8h | 27 | 0.03 | 2.4 | 3.18 | {'200': 27} |
| method reads | 36 | 13.95 | 14.68 | 14.77 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 9.7 | 1.0 | 0 | 181 |
| compute-gateway | 6.9 | 1.3 | 0 | 52 |
| dashcraft | 0.3 | 0.2 | 0 | 97 |
| doccraft | 37.2 | 3.3 | 0 | 83 |
| histcraft | 115.0 | 49.5 | 13 | 422 |
| histcraft-collector | 70.3 | 9.0 | 0 | 113 |
| histcraft-db | 12.6 | 4.0 | 0 | 96 |
| histcraft-gateway | 3.6 | 0.9 | 0 | 132 |
| installer | 12.4 | 3.1 | 0 | 29 |
| linkcraft | 101.5 | 19.8 | 4 | 519 |
| linkcraft-executor | 183.5 | 17.2 | 4 | 359 |
| llm-egress | 48.5 | 4.0 | 0 | 34 |
| modelcraft | 0.4 | 0.3 | 0 | 143 |
| modelcraft-executor | 0.7 | 0.5 | 0 | 203 |
| processcraft | 25.1 | 8.6 | 0 | 328 |
| proxy | 9.3 | 2.8 | 0 | 29 |
| simcraft | 35.1 | 21.3 | 0 | 265 |
