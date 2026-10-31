# Extreme load C2 B8-slots-2-r1 (2026-10-31T11:26Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 60 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 30.712 | ok |
| Analytics checks | 34.56 | ok |
| 9 methods (slowest) | 20.7 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 30 | 0.06 | 0.1 | 0.16 | {'200': 30} |
| person_display_values | 30 | 0.06 | 3.42 | 4.46 | {'200': 29, '429': 1} |
| person_trend_8h | 30 | 0.03 | 5.41 | 7.41 | {'200': 30} |
| method reads | 36 | 18.78 | 20.6 | 20.61 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 96.9 | 8.2 | 4 | 193 |
| compute-gateway | 9.6 | 0.9 | 0 | 58 |
| dashcraft | 34.3 | 2.7 | 0 | 96 |
| doccraft | 30.3 | 2.4 | 0 | 86 |
| histcraft | 123.9 | 45.9 | 21 | 407 |
| histcraft-collector | 114.3 | 13.9 | 4 | 139 |
| histcraft-db | 20.3 | 2.8 | 0 | 99 |
| histcraft-gateway | 1.8 | 0.5 | 0 | 133 |
| installer | 47.2 | 6.6 | 0 | 42 |
| linkcraft | 35.7 | 10.7 | 0 | 407 |
| linkcraft-executor | 131.4 | 23.9 | 9 | 202 |
| llm-egress | 39.1 | 2.8 | 0 | 17 |
| modelcraft | 31.4 | 2.5 | 0 | 169 |
| modelcraft-executor | 0.7 | 0.5 | 0 | 197 |
| processcraft | 37.3 | 8.0 | 0 | 585 |
| proxy | 9.3 | 1.7 | 0 | 30 |
| simcraft | 95.3 | 32.4 | 4 | 319 |
