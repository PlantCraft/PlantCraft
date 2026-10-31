# Extreme load C2 hunt-cache32-r1 (2026-10-31T14:01Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 61 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 16.879 | ok |
| Analytics checks | 23.32 | ok |
| 9 methods (slowest) | 25.5 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 32 | 0.08 | 0.35 | 1.0 | {'200': 32} |
| person_display_values | 32 | 0.07 | 0.73 | 0.85 | {'200': 32} |
| person_trend_8h | 32 | 0.04 | 3.57 | 5.15 | {'200': 32} |
| method reads | 36 | 19.57 | 25.3 | 25.44 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 53.1 | 10.6 | 0 | 238 |
| compute-gateway | 15.2 | 2.5 | 0 | 54 |
| dashcraft | 39.4 | 2.9 | 0 | 99 |
| doccraft | 37.2 | 2.7 | 0 | 89 |
| histcraft | 196.5 | 50.9 | 13 | 851 |
| histcraft-collector | 118.8 | 19.3 | 4 | 154 |
| histcraft-db | 20.2 | 4.4 | 0 | 137 |
| histcraft-gateway | 4.0 | 0.8 | 0 | 32 |
| installer | 51.2 | 6.6 | 0 | 26 |
| linkcraft | 86.8 | 17.5 | 0 | 792 |
| linkcraft-executor | 152.1 | 21.5 | 9 | 410 |
| llm-egress | 49.7 | 3.3 | 0 | 35 |
| modelcraft | 36.5 | 4.7 | 0 | 137 |
| modelcraft-executor | 5.6 | 1.1 | 0 | 10 |
| processcraft | 18.8 | 7.2 | 0 | 568 |
| proxy | 10.3 | 2.2 | 0 | 19 |
| simcraft | 72.3 | 27.5 | 0 | 306 |
