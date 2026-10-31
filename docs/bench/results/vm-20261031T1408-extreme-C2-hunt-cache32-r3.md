# Extreme load C2 hunt-cache32-r3 (2026-10-31T14:08Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 57 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 26.084 | ok |
| Analytics checks | 17.4 | ok |
| 9 methods (slowest) | 24.5 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 30 | 0.08 | 0.16 | 0.44 | {'200': 30} |
| person_display_values | 30 | 0.07 | 1.85 | 3.43 | {'429': 1, '200': 29} |
| person_trend_8h | 30 | 0.03 | 2.06 | 2.22 | {'200': 30} |
| method reads | 36 | 16.79 | 24.32 | 24.42 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 33.4 | 4.7 | 0 | 237 |
| compute-gateway | 16.3 | 3.4 | 0 | 49 |
| dashcraft | 16.0 | 1.4 | 0 | 103 |
| doccraft | 36.5 | 4.1 | 0 | 100 |
| histcraft | 200.2 | 49.7 | 22 | 910 |
| histcraft-collector | 97.2 | 9.4 | 4 | 129 |
| histcraft-db | 17.6 | 3.6 | 0 | 140 |
| histcraft-gateway | 0.8 | 0.4 | 0 | 32 |
| installer | 47.3 | 6.9 | 0 | 39 |
| linkcraft | 87.1 | 22.7 | 0 | 714 |
| linkcraft-executor | 119.1 | 31.4 | 13 | 406 |
| llm-egress | 39.0 | 2.8 | 0 | 18 |
| modelcraft | 33.4 | 2.7 | 0 | 136 |
| modelcraft-executor | 0.7 | 0.6 | 0 | 9 |
| processcraft | 27.9 | 8.9 | 0 | 580 |
| proxy | 12.7 | 2.4 | 0 | 19 |
| simcraft | 43.6 | 24.0 | 0 | 320 |
