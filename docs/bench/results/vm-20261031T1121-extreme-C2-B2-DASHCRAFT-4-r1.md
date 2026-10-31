# Extreme load C2 B2-DASHCRAFT-4-r1 (2026-10-31T11:21Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 51 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 24.439 | ok |
| Analytics checks | 27.6 | ok |
| 9 methods (slowest) | 19.4 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.04 | 0.3 | 0.34 | {'200': 27} |
| person_display_values | 27 | 0.06 | 3.5 | 3.67 | {'429': 3, '200': 24} |
| person_trend_8h | 27 | 0.03 | 2.36 | 2.54 | {'200': 27} |
| method reads | 36 | 17.6 | 19.27 | 19.33 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 14.7 | 1.6 | 0 | 181 |
| compute-gateway | 20.7 | 2.8 | 0 | 53 |
| dashcraft | 0.3 | 0.2 | 0 | 99 |
| doccraft | 0.3 | 0.2 | 0 | 84 |
| histcraft | 124.7 | 51.4 | 17 | 458 |
| histcraft-collector | 24.0 | 3.5 | 0 | 108 |
| histcraft-db | 21.1 | 3.8 | 0 | 102 |
| histcraft-gateway | 4.5 | 0.9 | 0 | 133 |
| installer | 64.2 | 11.3 | 0 | 37 |
| linkcraft | 96.0 | 18.5 | 4 | 601 |
| linkcraft-executor | 220.6 | 25.1 | 4 | 402 |
| llm-egress | 0.0 | 0.0 | 0 | 17 |
| modelcraft | 0.5 | 0.3 | 0 | 167 |
| modelcraft-executor | 6.5 | 1.0 | 0 | 198 |
| processcraft | 56.3 | 10.8 | 0 | 570 |
| proxy | 13.4 | 2.7 | 0 | 29 |
| simcraft | 77.8 | 27.0 | 0 | 316 |
