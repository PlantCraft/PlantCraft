# Extreme load C2 B2-HISTCRAFT-1-r1 (2026-10-31T11:14Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 25.825 | ok |
| Analytics checks | 27.76 | ok |
| 9 methods (slowest) | 19.3 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.06 | 0.12 | 0.13 | {'200': 27} |
| person_display_values | 27 | 0.07 | 4.47 | 4.57 | {'429': 2, '200': 25} |
| person_trend_8h | 27 | 0.03 | 5.3 | 5.5 | {'200': 27} |
| method reads | 36 | 17.4 | 19.2 | 19.25 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 18.5 | 2.8 | 0 | 181 |
| compute-gateway | 12.4 | 1.8 | 0 | 50 |
| dashcraft | 0.3 | 0.2 | 0 | 97 |
| doccraft | 0.3 | 0.2 | 0 | 88 |
| histcraft | 104.9 | 45.4 | 17 | 434 |
| histcraft-collector | 113.8 | 21.9 | 9 | 156 |
| histcraft-db | 10.9 | 1.9 | 0 | 92 |
| histcraft-gateway | 0.5 | 0.3 | 0 | 132 |
| installer | 52.1 | 9.3 | 0 | 25 |
| linkcraft | 49.1 | 7.9 | 0 | 580 |
| linkcraft-executor | 277.1 | 27.5 | 4 | 349 |
| llm-egress | 20.9 | 1.6 | 0 | 27 |
| modelcraft | 0.5 | 0.3 | 0 | 168 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 202 |
| processcraft | 12.9 | 4.4 | 0 | 561 |
| proxy | 9.4 | 2.3 | 0 | 29 |
| simcraft | 35.7 | 19.8 | 0 | 285 |
