# Extreme load C2 B2-LINKCRAFT_EXECUTOR-4-r1 (2026-10-31T11:12Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 60 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 27.475 | ok |
| Analytics checks | 33.05 | ok |
| 9 methods (slowest) | 20.2 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 30 | 0.05 | 0.17 | 0.21 | {'200': 30} |
| person_display_values | 30 | 0.07 | 3.82 | 5.58 | {'200': 29, '429': 1} |
| person_trend_8h | 30 | 0.02 | 4.79 | 4.87 | {'200': 30} |
| method reads | 36 | 16.99 | 20.05 | 20.12 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 25.6 | 3.9 | 0 | 180 |
| compute-gateway | 4.1 | 0.6 | 0 | 50 |
| dashcraft | 50.7 | 4.7 | 0 | 111 |
| doccraft | 9.5 | 0.9 | 0 | 98 |
| histcraft | 124.3 | 43.8 | 17 | 396 |
| histcraft-collector | 100.7 | 10.4 | 4 | 158 |
| histcraft-db | 18.0 | 3.4 | 0 | 134 |
| histcraft-gateway | 3.3 | 0.6 | 0 | 132 |
| installer | 53.6 | 11.3 | 0 | 37 |
| linkcraft | 93.4 | 14.9 | 0 | 535 |
| linkcraft-executor | 246.9 | 30.7 | 9 | 325 |
| llm-egress | 0.0 | 0.0 | 0 | 17 |
| modelcraft | 40.2 | 5.5 | 0 | 162 |
| modelcraft-executor | 0.8 | 0.5 | 0 | 201 |
| processcraft | 53.5 | 9.8 | 0 | 560 |
| proxy | 8.7 | 2.0 | 0 | 29 |
| simcraft | 98.7 | 26.7 | 4 | 312 |
