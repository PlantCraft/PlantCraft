# Extreme load C2 B2-DASHCRAFT-1-r1 (2026-10-31T11:18Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 50 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 23.03 | ok |
| Analytics checks | 25.9 | ok |
| 9 methods (slowest) | 16.7 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.05 | 0.07 | 0.08 | {'200': 27} |
| person_display_values | 27 | 0.07 | 3.53 | 3.78 | {'200': 26, '429': 1} |
| person_trend_8h | 27 | 0.02 | 3.26 | 3.3 | {'200': 27} |
| method reads | 36 | 13.88 | 16.54 | 16.67 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 39.0 | 9.1 | 0 | 182 |
| compute-gateway | 14.6 | 2.3 | 0 | 50 |
| dashcraft | 0.2 | 0.2 | 0 | 96 |
| doccraft | 6.8 | 0.8 | 0 | 83 |
| histcraft | 118.0 | 47.9 | 17 | 381 |
| histcraft-collector | 120.2 | 17.2 | 4 | 159 |
| histcraft-db | 18.8 | 3.1 | 0 | 100 |
| histcraft-gateway | 0.4 | 0.3 | 0 | 136 |
| installer | 46.4 | 10.0 | 0 | 25 |
| linkcraft | 34.5 | 7.3 | 0 | 555 |
| linkcraft-executor | 272.5 | 27.8 | 4 | 393 |
| llm-egress | 24.1 | 2.4 | 0 | 29 |
| modelcraft | 0.5 | 0.3 | 0 | 165 |
| modelcraft-executor | 4.9 | 0.9 | 0 | 202 |
| processcraft | 24.4 | 7.0 | 0 | 566 |
| proxy | 8.8 | 2.1 | 0 | 29 |
| simcraft | 27.7 | 20.1 | 0 | 272 |
