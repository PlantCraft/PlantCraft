# Extreme load C2 workers-auto (2026-10-31T10:29Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 51 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 11.901 | ok |
| Analytics checks | 14.19 | ok |
| 9 methods (slowest) | 11.7 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.07 | 0.14 | 0.18 | {'200': 27} |
| person_display_values | 27 | 0.07 | 2.83 | 3.5 | {'200': 27} |
| person_trend_8h | 27 | 0.03 | 2.24 | 2.69 | {'200': 27} |
| method reads | 36 | 11.24 | 11.58 | 11.59 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 53.4 | 5.6 | 0 | 189 |
| compute-gateway | 14.1 | 1.9 | 0 | 35 |
| dashcraft | 1.3 | 0.3 | 0 | 102 |
| doccraft | 0.3 | 0.2 | 0 | 90 |
| histcraft | 122.8 | 38.0 | 9 | 412 |
| histcraft-collector | 112.7 | 18.5 | 4 | 165 |
| histcraft-db | 17.7 | 5.8 | 0 | 133 |
| histcraft-gateway | 0.6 | 0.4 | 0 | 32 |
| installer | 43.5 | 6.2 | 0 | 91 |
| linkcraft | 88.4 | 16.0 | 0 | 417 |
| linkcraft-executor | 231.2 | 33.1 | 9 | 334 |
| llm-egress | 13.1 | 1.0 | 0 | 26 |
| modelcraft | 0.6 | 0.3 | 0 | 121 |
| modelcraft-executor | 6.2 | 1.0 | 0 | 20 |
| processcraft | 41.2 | 14.8 | 0 | 521 |
| proxy | 14.6 | 1.8 | 0 | 21 |
| simcraft | 68.6 | 16.4 | 0 | 253 |
