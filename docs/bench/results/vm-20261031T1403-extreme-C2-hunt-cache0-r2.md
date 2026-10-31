# Extreme load C2 hunt-cache0-r2 (2026-10-31T14:03Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 69 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 19.593 | ok |
| Analytics checks | 26.98 | ok |
| 9 methods (slowest) | 35.1 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 36 | 0.1 | 0.37 | 0.38 | {'200': 36} |
| person_display_values | 36 | 0.09 | 3.01 | 4.72 | {'200': 36} |
| person_trend_8h | 36 | 0.07 | 2.23 | 2.27 | {'200': 36} |
| method reads | 36 | 27.35 | 34.9 | 34.96 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 28.7 | 5.3 | 0 | 228 |
| compute-gateway | 10.3 | 1.7 | 0 | 55 |
| dashcraft | 15.7 | 1.7 | 0 | 98 |
| doccraft | 42.2 | 2.7 | 0 | 89 |
| histcraft | 153.8 | 62.4 | 26 | 761 |
| histcraft-collector | 89.8 | 11.9 | 0 | 124 |
| histcraft-db | 20.9 | 5.4 | 0 | 137 |
| histcraft-gateway | 2.4 | 0.5 | 0 | 32 |
| installer | 55.5 | 11.9 | 0 | 26 |
| linkcraft | 109.3 | 19.6 | 4 | 692 |
| linkcraft-executor | 134.1 | 23.6 | 4 | 398 |
| llm-egress | 45.4 | 2.7 | 0 | 35 |
| modelcraft | 37.9 | 3.8 | 0 | 134 |
| modelcraft-executor | 5.0 | 0.8 | 0 | 9 |
| processcraft | 47.0 | 13.9 | 0 | 572 |
| proxy | 14.7 | 3.9 | 0 | 20 |
| simcraft | 83.6 | 30.5 | 0 | 345 |
