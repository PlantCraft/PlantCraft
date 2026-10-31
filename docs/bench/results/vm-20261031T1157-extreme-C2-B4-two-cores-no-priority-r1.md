# Extreme load C2 B4-two-cores-no-priority-r1 (2026-10-31T11:57Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 66 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 33.465 | ok |
| Analytics checks | 40.15 | ok |
| 9 methods (slowest) | 21.0 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 32 | 0.07 | 0.25 | 0.26 | {'200': 32} |
| person_display_values | 32 | 0.08 | 5.66 | 6.4 | {'200': 32} |
| person_trend_8h | 32 | 0.03 | 4.68 | 6.15 | {'200': 32} |
| method reads | 36 | 19.83 | 20.89 | 20.94 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 35.3 | 6.0 | 0 | 225 |
| compute-gateway | 15.9 | 2.7 | 0 | 61 |
| dashcraft | 0.3 | 0.2 | 0 | 100 |
| doccraft | 0.3 | 0.2 | 0 | 89 |
| histcraft | 122.5 | 43.7 | 13 | 564 |
| histcraft-collector | 68.1 | 11.2 | 0 | 148 |
| histcraft-db | 28.9 | 4.4 | 0 | 98 |
| histcraft-gateway | 4.5 | 0.7 | 0 | 130 |
| installer | 43.1 | 7.9 | 0 | 37 |
| linkcraft | 17.4 | 6.1 | 0 | 691 |
| linkcraft-executor | 155.9 | 22.1 | 4 | 375 |
| llm-egress | 27.4 | 1.7 | 0 | 26 |
| modelcraft | 31.6 | 3.5 | 0 | 178 |
| modelcraft-executor | 4.8 | 0.7 | 0 | 193 |
| processcraft | 29.3 | 8.0 | 0 | 580 |
| proxy | 8.4 | 1.8 | 0 | 30 |
| simcraft | 99.8 | 33.6 | 4 | 338 |
