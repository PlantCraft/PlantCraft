# Extreme load C2 B8-slots-1-r1 (2026-10-31T11:24Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 66 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 32.566 | ok |
| Analytics checks | 39.66 | ok |
| 9 methods (slowest) | 20.0 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 33 | 0.05 | 0.09 | 0.29 | {'200': 33} |
| person_display_values | 33 | 0.06 | 3.45 | 3.95 | {'200': 32, '429': 1} |
| person_trend_8h | 33 | 0.03 | 4.69 | 5.27 | {'200': 33} |
| method reads | 36 | 17.34 | 19.89 | 19.94 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 26.1 | 4.4 | 0 | 181 |
| compute-gateway | 18.6 | 2.7 | 0 | 58 |
| dashcraft | 41.4 | 5.3 | 0 | 95 |
| doccraft | 15.8 | 1.2 | 0 | 96 |
| histcraft | 126.7 | 43.2 | 21 | 417 |
| histcraft-collector | 54.0 | 6.1 | 0 | 95 |
| histcraft-db | 30.1 | 3.9 | 0 | 95 |
| histcraft-gateway | 1.9 | 0.4 | 0 | 133 |
| installer | 59.8 | 10.9 | 0 | 38 |
| linkcraft | 59.7 | 13.2 | 0 | 394 |
| linkcraft-executor | 101.3 | 26.3 | 16 | 134 |
| llm-egress | 44.7 | 2.8 | 0 | 34 |
| modelcraft | 43.8 | 6.8 | 0 | 176 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 197 |
| processcraft | 35.9 | 9.6 | 0 | 583 |
| proxy | 9.1 | 1.4 | 0 | 29 |
| simcraft | 29.5 | 21.0 | 0 | 293 |
