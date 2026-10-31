# Extreme load C2 B2-machine-4c-hist1-r1 (2026-10-31T11:54Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 60 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 30.453 | ok |
| Analytics checks | 34.46 | ok |
| 9 methods (slowest) | 24.1 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 30 | 0.06 | 0.12 | 0.21 | {'200': 30} |
| person_display_values | 30 | 0.06 | 4.42 | 4.81 | {'429': 1, '200': 29} |
| person_trend_8h | 30 | 0.02 | 3.07 | 3.79 | {'200': 30} |
| method reads | 36 | 21.49 | 23.93 | 24.1 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 42.4 | 7.4 | 0 | 226 |
| compute-gateway | 17.1 | 1.7 | 0 | 61 |
| dashcraft | 0.3 | 0.2 | 0 | 98 |
| doccraft | 10.2 | 0.9 | 0 | 88 |
| histcraft | 133.7 | 55.8 | 26 | 495 |
| histcraft-collector | 115.4 | 13.7 | 4 | 148 |
| histcraft-db | 31.5 | 4.6 | 0 | 97 |
| histcraft-gateway | 4.9 | 0.8 | 0 | 130 |
| installer | 25.3 | 4.5 | 0 | 35 |
| linkcraft | 89.3 | 11.6 | 0 | 680 |
| linkcraft-executor | 184.5 | 18.4 | 4 | 363 |
| llm-egress | 39.1 | 2.6 | 0 | 17 |
| modelcraft | 27.6 | 2.1 | 0 | 180 |
| modelcraft-executor | 5.3 | 0.9 | 0 | 195 |
| processcraft | 40.8 | 7.5 | 0 | 578 |
| proxy | 8.4 | 1.3 | 0 | 31 |
| simcraft | 96.0 | 34.7 | 0 | 338 |
