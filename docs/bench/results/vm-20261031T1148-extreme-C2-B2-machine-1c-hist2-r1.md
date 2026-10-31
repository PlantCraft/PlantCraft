# Extreme load C2 B2-machine-1c-hist2-r1 (2026-10-31T11:48Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 923 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 85.276 | ok |
| Analytics checks | None | did not start |
| 9 methods (slowest) | 37.1 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 496 | 0.13 | 0.54 | 1.83 | {'200': 481, '401': 15} |
| person_display_values | 496 | 0.12 | 0.66 | 7.67 | {'200': 478, '429': 3, '401': 15} |
| person_trend_8h | 496 | 0.05 | 0.3 | 10.24 | {'200': 480, '502': 1, '401': 15} |
| method reads | 36 | 30.4 | 36.92 | 37.08 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 55.2 | 5.8 | 0 | 238 |
| compute-gateway | 20.8 | 0.9 | 0 | 69 |
| dashcraft | 38.0 | 2.4 | 0 | 111 |
| doccraft | 42.2 | 2.9 | 0 | 102 |
| histcraft | 63.9 | 8.3 | 0 | 717 |
| histcraft-collector | 76.4 | 8.1 | 0 | 161 |
| histcraft-db | 18.1 | 2.3 | 0 | 130 |
| histcraft-gateway | 3.9 | 0.4 | 0 | 130 |
| installer | 57.1 | 5.1 | 0 | 45 |
| linkcraft | 56.2 | 7.2 | 0 | 600 |
| linkcraft-executor | 48.8 | 3.3 | 0 | 340 |
| llm-egress | 44.1 | 2.0 | 0 | 34 |
| modelcraft | 38.7 | 1.9 | 0 | 180 |
| modelcraft-executor | 5.9 | 0.6 | 0 | 198 |
| processcraft | 39.2 | 5.9 | 0 | 592 |
| proxy | 8.2 | 0.8 | 0 | 30 |
| simcraft | 91.0 | 21.9 | 0 | 338 |
