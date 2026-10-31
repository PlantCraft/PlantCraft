# Extreme load C2 B4-two-cores-priority-r1 (2026-10-31T13:24Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 82 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics checks | 44.03 | ok |
| Analytics round | 55.62 | ok |
| 9 methods (slowest) | 27.4 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 39 | 0.13 | 1.44 | 1.52 | {'200': 39} |
| person_display_values | 39 | 0.07 | 4.26 | 5.11 | {'200': 38, '429': 1} |
| person_trend_8h | 39 | 0.03 | 4.13 | 4.58 | {'200': 38, '502': 1} |
| method reads | 36 | 21.31 | 27.24 | 27.34 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 40.4 | 3.2 | 0 | 182 |
| compute-gateway | 18.4 | 2.5 | 0 | 50 |
| dashcraft | 19.3 | 1.2 | 0 | 104 |
| doccraft | 33.9 | 2.5 | 0 | 90 |
| histcraft | 109.9 | 42.2 | 21 | 580 |
| histcraft-collector | 87.7 | 9.5 | 0 | 140 |
| histcraft-db | 18.9 | 4.2 | 0 | 123 |
| histcraft-gateway | 3.2 | 0.6 | 0 | 33 |
| installer | 49.7 | 5.9 | 0 | 29 |
| linkcraft | 42.3 | 10.8 | 0 | 502 |
| linkcraft-executor | 153.9 | 28.9 | 13 | 348 |
| llm-egress | 35.0 | 3.0 | 0 | 19 |
| modelcraft | 15.1 | 1.0 | 0 | 137 |
| modelcraft-executor | 7.8 | 0.7 | 0 | 9 |
| processcraft | 28.6 | 8.4 | 0 | 543 |
| proxy | 16.3 | 2.2 | 0 | 17 |
| simcraft | 101.2 | 28.7 | 4 | 317 |
