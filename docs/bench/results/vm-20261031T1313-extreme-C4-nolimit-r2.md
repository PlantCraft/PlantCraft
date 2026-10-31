# Extreme load C4 nolimit-r2 (2026-10-31T13:13Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 20 people, rounds on, 167 signals x 24 h, raw. Run 923 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 10.26 | ok |
| Analytics checks | None | did not start |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 3557 | 0.08 | 0.24 | 0.82 | {'200': 3468, '401': 89} |
| person_display_values | 3557 | 0.05 | 0.12 | 0.99 | {'200': 1800, '429': 1667, '502': 1, '401': 89} |
| person_trend_8h | 3557 | 0.04 | 0.09 | 0.47 | {'200': 3468, '401': 89} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 78.0 | 9.2 | 0 | 242 |
| compute-gateway | 19.2 | 0.9 | 0 | 53 |
| dashcraft | 57.1 | 2.9 | 0 | 118 |
| doccraft | 61.5 | 3.5 | 0 | 114 |
| histcraft | 91.2 | 19.9 | 0 | 436 |
| histcraft-collector | 121.5 | 13.4 | 51 | 282 |
| histcraft-db | 41.6 | 4.9 | 0 | 186 |
| histcraft-gateway | 5.0 | 0.7 | 0 | 33 |
| installer | 63.4 | 7.4 | 0 | 118 |
| linkcraft | 117.4 | 29.3 | 22 | 722 |
| linkcraft-executor | 116.3 | 4.2 | 22 | 396 |
| llm-egress | 50.6 | 2.3 | 0 | 36 |
| modelcraft | 57.1 | 3.2 | 0 | 148 |
| modelcraft-executor | 9.2 | 0.7 | 0 | 20 |
| processcraft | 74.4 | 11.3 | 0 | 508 |
| proxy | 12.1 | 4.1 | 0 | 19 |
| simcraft | 102.3 | 31.5 | 34 | 360 |
