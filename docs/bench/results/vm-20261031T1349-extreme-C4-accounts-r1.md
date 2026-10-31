# Extreme load C4 accounts-r1 (2026-10-31T13:49Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 20 people, rounds on, 167 signals x 24 h, raw. Run 59 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 12.872 | ok |
| Analytics checks | 16.49 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 210 | 0.08 | 0.37 | 0.82 | {'200': 210} |
| person_display_values | 210 | 0.07 | 0.26 | 0.66 | {'200': 210} |
| person_trend_8h | 210 | 0.03 | 0.24 | 0.48 | {'200': 210} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 32.4 | 3.3 | 0 | 184 |
| compute-gateway | 25.4 | 4.8 | 0 | 53 |
| dashcraft | 42.3 | 3.2 | 0 | 103 |
| doccraft | 0.3 | 0.2 | 0 | 86 |
| histcraft | 121.1 | 34.4 | 9 | 458 |
| histcraft-collector | 63.2 | 10.6 | 0 | 174 |
| histcraft-db | 37.8 | 7.3 | 0 | 117 |
| histcraft-gateway | 3.5 | 0.6 | 0 | 33 |
| installer | 57.0 | 5.2 | 0 | 94 |
| linkcraft | 102.3 | 36.9 | 4 | 651 |
| linkcraft-executor | 179.1 | 31.0 | 9 | 375 |
| llm-egress | 16.0 | 1.1 | 0 | 27 |
| modelcraft | 37.1 | 3.5 | 0 | 129 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 19 |
| processcraft | 164.1 | 34.7 | 4 | 486 |
| proxy | 7.4 | 4.0 | 0 | 18 |
| simcraft | 72.5 | 15.7 | 0 | 260 |
