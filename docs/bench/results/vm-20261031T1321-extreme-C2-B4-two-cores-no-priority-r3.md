# Extreme load C2 B4-two-cores-no-priority-r3 (2026-10-31T13:21Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 82 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 44.025 | ok |
| Analytics checks | 56.57 | ok |
| 9 methods (slowest) | 28.4 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 37 | 0.12 | 0.5 | 0.61 | {'200': 37} |
| person_display_values | 37 | 0.12 | 4.43 | 6.11 | {'429': 1, '200': 36} |
| person_trend_8h | 37 | 0.04 | 6.23 | 8.12 | {'200': 36, '502': 1} |
| method reads | 36 | 22.83 | 28.07 | 28.35 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 35.4 | 6.1 | 0 | 191 |
| compute-gateway | 8.6 | 1.4 | 0 | 50 |
| dashcraft | 0.3 | 0.2 | 0 | 102 |
| doccraft | 2.7 | 0.3 | 0 | 90 |
| histcraft | 105.1 | 41.7 | 13 | 624 |
| histcraft-collector | 50.0 | 11.5 | 0 | 196 |
| histcraft-db | 17.2 | 3.5 | 0 | 134 |
| histcraft-gateway | 0.5 | 0.3 | 0 | 32 |
| installer | 30.8 | 4.3 | 0 | 40 |
| linkcraft | 76.2 | 14.3 | 0 | 786 |
| linkcraft-executor | 153.3 | 21.3 | 4 | 390 |
| llm-egress | 40.6 | 3.0 | 0 | 28 |
| modelcraft | 39.5 | 6.8 | 0 | 146 |
| modelcraft-executor | 0.6 | 0.4 | 0 | 20 |
| processcraft | 43.6 | 12.2 | 0 | 594 |
| proxy | 8.4 | 1.4 | 0 | 20 |
| simcraft | 47.0 | 25.0 | 0 | 298 |
