# Extreme load C2 B2-HISTCRAFT-2-r1 (2026-10-31T11:15Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 23.148 | ok |
| Analytics checks | 26.42 | ok |
| 9 methods (slowest) | 17.2 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 28 | 0.05 | 0.09 | 0.1 | {'200': 28} |
| person_display_values | 28 | 0.08 | 3.33 | 4.31 | {'200': 26, '429': 2} |
| person_trend_8h | 28 | 0.03 | 2.62 | 2.7 | {'200': 28} |
| method reads | 36 | 15.72 | 17.05 | 17.12 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 0.7 | 0.3 | 0 | 181 |
| compute-gateway | 5.2 | 0.9 | 0 | 51 |
| dashcraft | 41.2 | 4.7 | 0 | 98 |
| doccraft | 1.4 | 0.3 | 0 | 88 |
| histcraft | 148.3 | 49.9 | 17 | 400 |
| histcraft-collector | 95.5 | 12.8 | 4 | 94 |
| histcraft-db | 27.8 | 5.9 | 0 | 94 |
| histcraft-gateway | 0.5 | 0.3 | 0 | 134 |
| installer | 30.4 | 5.9 | 0 | 28 |
| linkcraft | 34.9 | 8.9 | 0 | 558 |
| linkcraft-executor | 247.6 | 25.2 | 4 | 362 |
| llm-egress | 52.5 | 4.0 | 0 | 34 |
| modelcraft | 36.0 | 4.1 | 0 | 170 |
| modelcraft-executor | 7.1 | 1.0 | 0 | 202 |
| processcraft | 49.1 | 12.9 | 0 | 561 |
| proxy | 21.2 | 3.2 | 0 | 30 |
| simcraft | 35.0 | 19.3 | 0 | 268 |
