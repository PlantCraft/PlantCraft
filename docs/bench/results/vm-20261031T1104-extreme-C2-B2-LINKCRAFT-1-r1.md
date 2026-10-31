# Extreme load C2 B2-LINKCRAFT-1-r1 (2026-10-31T11:04Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 24.581 | ok |
| Analytics checks | 25.25 | ok |
| 9 methods (slowest) | 17.4 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 28 | 0.06 | 0.22 | 0.28 | {'200': 28} |
| person_display_values | 28 | 0.07 | 3.9 | 5.89 | {'200': 27, '429': 1} |
| person_trend_8h | 28 | 0.03 | 2.58 | 3.48 | {'200': 28} |
| method reads | 36 | 13.96 | 17.27 | 17.35 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 51.5 | 10.0 | 0 | 181 |
| compute-gateway | 8.6 | 1.1 | 0 | 51 |
| dashcraft | 0.2 | 0.2 | 0 | 99 |
| doccraft | 38.9 | 4.7 | 0 | 85 |
| histcraft | 123.4 | 47.1 | 17 | 418 |
| histcraft-collector | 47.8 | 5.6 | 0 | 96 |
| histcraft-db | 21.8 | 3.8 | 0 | 129 |
| histcraft-gateway | 2.9 | 0.5 | 0 | 131 |
| installer | 23.8 | 5.6 | 0 | 32 |
| linkcraft | 33.6 | 10.7 | 0 | 470 |
| linkcraft-executor | 185.3 | 28.4 | 8 | 379 |
| llm-egress | 27.9 | 2.1 | 0 | 17 |
| modelcraft | 14.1 | 1.4 | 0 | 165 |
| modelcraft-executor | 0.7 | 0.5 | 0 | 202 |
| processcraft | 25.4 | 6.7 | 0 | 545 |
| proxy | 11.2 | 2.7 | 0 | 29 |
| simcraft | 98.1 | 34.0 | 4 | 315 |
