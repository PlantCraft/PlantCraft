# Extreme load C4 accounts-r3 (2026-10-31T13:52Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 20 people, rounds on, 167 signals x 24 h, raw. Run 66 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 13.902 | ok |
| Analytics checks | 19.43 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 232 | 0.09 | 0.43 | 0.87 | {'200': 232} |
| person_display_values | 232 | 0.08 | 0.23 | 0.59 | {'200': 232} |
| person_trend_8h | 232 | 0.03 | 0.26 | 0.74 | {'200': 232} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 71.7 | 11.5 | 0 | 196 |
| compute-gateway | 16.5 | 2.0 | 0 | 48 |
| dashcraft | 0.3 | 0.2 | 0 | 103 |
| doccraft | 53.8 | 5.2 | 0 | 97 |
| histcraft | 110.9 | 33.4 | 4 | 474 |
| histcraft-collector | 89.9 | 14.9 | 0 | 178 |
| histcraft-db | 30.8 | 6.6 | 0 | 121 |
| histcraft-gateway | 0.8 | 0.4 | 0 | 33 |
| installer | 44.0 | 9.1 | 0 | 106 |
| linkcraft | 98.8 | 32.1 | 4 | 737 |
| linkcraft-executor | 162.5 | 21.5 | 4 | 383 |
| llm-egress | 22.2 | 2.0 | 0 | 26 |
| modelcraft | 9.7 | 1.2 | 0 | 129 |
| modelcraft-executor | 6.5 | 0.9 | 0 | 19 |
| processcraft | 147.8 | 39.1 | 9 | 568 |
| proxy | 7.3 | 4.8 | 0 | 18 |
| simcraft | 97.6 | 26.8 | 0 | 277 |
