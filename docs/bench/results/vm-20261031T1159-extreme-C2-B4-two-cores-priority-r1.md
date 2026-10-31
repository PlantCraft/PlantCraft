# Extreme load C2 B4-two-cores-priority-r1 (2026-10-31T11:59Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 61 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics checks | 29.76 | ok |
| Analytics round | 38.558 | ok |
| 9 methods (slowest) | 19.8 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 30 | 0.1 | 1.11 | 1.21 | {'200': 30} |
| person_display_values | 30 | 0.08 | 7.67 | 7.98 | {'200': 29, '429': 1} |
| person_trend_8h | 30 | 0.03 | 3.47 | 5.5 | {'200': 30} |
| method reads | 36 | 18.16 | 19.39 | 19.81 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 37.8 | 6.0 | 0 | 226 |
| compute-gateway | 13.0 | 2.4 | 0 | 61 |
| dashcraft | 34.7 | 3.7 | 0 | 114 |
| doccraft | 36.8 | 2.6 | 0 | 90 |
| histcraft | 112.5 | 40.2 | 17 | 568 |
| histcraft-collector | 43.8 | 6.1 | 0 | 151 |
| histcraft-db | 16.9 | 4.3 | 0 | 100 |
| histcraft-gateway | 0.5 | 0.3 | 0 | 132 |
| installer | 38.9 | 7.3 | 0 | 34 |
| linkcraft | 53.3 | 8.9 | 0 | 547 |
| linkcraft-executor | 136.8 | 19.0 | 8 | 349 |
| llm-egress | 32.4 | 2.2 | 0 | 17 |
| modelcraft | 0.5 | 0.3 | 0 | 165 |
| modelcraft-executor | 0.6 | 0.4 | 0 | 10 |
| processcraft | 31.8 | 10.2 | 0 | 544 |
| proxy | 11.6 | 1.6 | 0 | 25 |
| simcraft | 99.2 | 27.0 | 0 | 337 |
