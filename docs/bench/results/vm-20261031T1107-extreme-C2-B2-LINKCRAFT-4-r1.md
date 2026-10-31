# Extreme load C2 B2-LINKCRAFT-4-r1 (2026-10-31T11:07Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 23.646 | ok |
| Analytics checks | 26.36 | ok |
| 9 methods (slowest) | 19.1 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 28 | 0.06 | 0.13 | 0.22 | {'200': 28} |
| person_display_values | 28 | 0.08 | 5.16 | 5.62 | {'200': 27, '429': 1} |
| person_trend_8h | 28 | 0.03 | 1.75 | 1.87 | {'200': 28} |
| method reads | 36 | 17.33 | 19.0 | 19.06 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 32.7 | 3.0 | 0 | 180 |
| compute-gateway | 18.7 | 2.2 | 0 | 50 |
| dashcraft | 0.9 | 0.3 | 0 | 100 |
| doccraft | 34.4 | 2.9 | 0 | 97 |
| histcraft | 125.9 | 46.2 | 17 | 411 |
| histcraft-collector | 35.8 | 4.7 | 0 | 113 |
| histcraft-db | 23.7 | 4.8 | 0 | 130 |
| histcraft-gateway | 0.5 | 0.4 | 0 | 132 |
| installer | 26.2 | 3.9 | 0 | 40 |
| linkcraft | 114.1 | 17.7 | 4 | 428 |
| linkcraft-executor | 240.2 | 23.5 | 4 | 385 |
| llm-egress | 41.0 | 3.2 | 0 | 34 |
| modelcraft | 2.0 | 0.4 | 0 | 167 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 202 |
| processcraft | 29.0 | 7.2 | 0 | 553 |
| proxy | 4.7 | 1.1 | 0 | 29 |
| simcraft | 65.8 | 24.1 | 0 | 292 |
