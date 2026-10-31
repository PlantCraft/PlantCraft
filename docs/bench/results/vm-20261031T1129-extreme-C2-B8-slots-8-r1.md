# Extreme load C2 B8-slots-8-r1 (2026-10-31T11:29Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 26.978 | ok |
| Analytics checks | 27.29 | ok |
| 9 methods (slowest) | 17.5 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.06 | 0.28 | 0.35 | {'200': 27} |
| person_display_values | 27 | 0.06 | 3.89 | 4.06 | {'429': 2, '200': 25} |
| person_trend_8h | 27 | 0.02 | 2.89 | 3.04 | {'200': 27} |
| method reads | 36 | 16.22 | 17.36 | 17.45 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 41.1 | 8.9 | 0 | 225 |
| compute-gateway | 8.2 | 1.0 | 0 | 61 |
| dashcraft | 0.2 | 0.2 | 0 | 96 |
| doccraft | 37.5 | 5.1 | 0 | 87 |
| histcraft | 128.6 | 45.8 | 13 | 448 |
| histcraft-collector | 77.3 | 7.5 | 0 | 96 |
| histcraft-db | 15.2 | 3.8 | 0 | 106 |
| histcraft-gateway | 0.7 | 0.4 | 0 | 131 |
| installer | 60.4 | 6.0 | 0 | 26 |
| linkcraft | 86.6 | 16.3 | 0 | 483 |
| linkcraft-executor | 314.4 | 41.5 | 9 | 615 |
| llm-egress | 9.9 | 0.8 | 0 | 26 |
| modelcraft | 0.4 | 0.3 | 0 | 169 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 197 |
| processcraft | 24.3 | 6.5 | 0 | 571 |
| proxy | 17.2 | 3.0 | 0 | 29 |
| simcraft | 95.0 | 31.7 | 0 | 336 |
