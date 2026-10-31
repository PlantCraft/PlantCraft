# Extreme load C2 workers-1 (2026-10-31T10:30Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 48 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 16.374 | ok |
| Analytics checks | 21.01 | ok |
| 9 methods (slowest) | 13.0 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 25 | 0.06 | 0.17 | 0.24 | {'200': 25} |
| person_display_values | 25 | 0.07 | 4.13 | 4.18 | {'200': 24, '429': 1} |
| person_trend_8h | 25 | 0.04 | 2.36 | 3.15 | {'200': 25} |
| method reads | 36 | 12.5 | 12.86 | 12.96 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 47.1 | 4.2 | 0 | 188 |
| compute-gateway | 7.5 | 1.0 | 0 | 36 |
| dashcraft | 0.3 | 0.2 | 0 | 103 |
| doccraft | 0.2 | 0.2 | 0 | 90 |
| histcraft | 163.7 | 39.9 | 9 | 238 |
| histcraft-collector | 103.5 | 13.4 | 4 | 156 |
| histcraft-db | 15.3 | 4.7 | 0 | 126 |
| histcraft-gateway | 3.9 | 0.7 | 0 | 32 |
| installer | 63.6 | 6.7 | 0 | 81 |
| linkcraft | 42.4 | 8.6 | 0 | 449 |
| linkcraft-executor | 215.1 | 22.7 | 4 | 344 |
| llm-egress | 6.1 | 0.5 | 0 | 17 |
| modelcraft | 0.4 | 0.3 | 0 | 130 |
| modelcraft-executor | 0.7 | 0.5 | 0 | 20 |
| processcraft | 30.7 | 8.2 | 0 | 523 |
| proxy | 17.7 | 2.8 | 0 | 21 |
| simcraft | 99.6 | 33.9 | 13 | 291 |
