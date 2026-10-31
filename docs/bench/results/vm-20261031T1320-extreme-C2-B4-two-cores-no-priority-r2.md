# Extreme load C2 B4-two-cores-no-priority-r2 (2026-10-31T13:20Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 81 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 45.702 | ok |
| Analytics checks | 54.63 | ok |
| 9 methods (slowest) | 29.2 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 40 | 0.07 | 0.47 | 0.61 | {'200': 40} |
| person_display_values | 40 | 0.07 | 5.1 | 8.62 | {'200': 40} |
| person_trend_8h | 40 | 0.04 | 3.03 | 4.49 | {'200': 40} |
| method reads | 36 | 23.82 | 29.02 | 29.11 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 45.6 | 5.3 | 0 | 195 |
| compute-gateway | 9.6 | 1.1 | 0 | 49 |
| dashcraft | 8.6 | 1.0 | 0 | 102 |
| doccraft | 10.1 | 0.8 | 0 | 89 |
| histcraft | 106.9 | 36.5 | 17 | 565 |
| histcraft-collector | 68.1 | 7.1 | 0 | 178 |
| histcraft-db | 17.1 | 3.0 | 0 | 132 |
| histcraft-gateway | 3.9 | 0.6 | 0 | 32 |
| installer | 49.8 | 7.9 | 0 | 32 |
| linkcraft | 49.6 | 10.1 | 0 | 740 |
| linkcraft-executor | 101.5 | 17.9 | 4 | 390 |
| llm-egress | 30.7 | 1.5 | 0 | 31 |
| modelcraft | 30.8 | 3.9 | 0 | 137 |
| modelcraft-executor | 5.7 | 0.9 | 0 | 22 |
| processcraft | 42.6 | 11.0 | 0 | 600 |
| proxy | 13.7 | 2.2 | 0 | 20 |
| simcraft | 86.9 | 28.7 | 0 | 296 |
