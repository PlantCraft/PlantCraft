# Extreme load C2 B4-two-cores-no-priority-r1 (2026-10-31T13:18Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 381 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 37.639 | ok |
| Analytics checks | 27.25 | ok |
| 9 methods (slowest) | 28.5 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 210 | 0.08 | 0.25 | 0.62 | {'200': 210} |
| person_display_values | 210 | 0.06 | 0.34 | 14.52 | {'200': 207, '429': 3} |
| person_trend_8h | 210 | 0.04 | 0.12 | 13.47 | {'200': 210} |
| method reads | 36 | 24.48 | 28.48 | 28.49 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 74.2 | 9.5 | 0 | 184 |
| compute-gateway | 18.6 | 1.1 | 0 | 48 |
| dashcraft | 40.9 | 1.4 | 0 | 113 |
| doccraft | 30.5 | 1.5 | 0 | 99 |
| histcraft | 114.8 | 13.6 | 13 | 606 |
| histcraft-collector | 102.5 | 9.0 | 8 | 198 |
| histcraft-db | 37.0 | 3.0 | 0 | 130 |
| histcraft-gateway | 4.0 | 0.5 | 0 | 32 |
| installer | 59.3 | 6.8 | 0 | 36 |
| linkcraft | 91.4 | 10.0 | 0 | 789 |
| linkcraft-executor | 149.5 | 6.9 | 4 | 379 |
| llm-egress | 52.2 | 2.3 | 0 | 35 |
| modelcraft | 45.7 | 3.7 | 0 | 134 |
| modelcraft-executor | 6.8 | 0.7 | 0 | 20 |
| processcraft | 63.9 | 5.1 | 0 | 591 |
| proxy | 6.7 | 1.0 | 0 | 19 |
| simcraft | 101.0 | 23.3 | 4 | 275 |
