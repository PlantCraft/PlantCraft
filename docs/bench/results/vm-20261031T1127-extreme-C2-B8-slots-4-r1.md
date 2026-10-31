# Extreme load C2 B8-slots-4-r1 (2026-10-31T11:27Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 27.486 | ok |
| Analytics checks | 27.09 | ok |
| 9 methods (slowest) | 19.8 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 28 | 0.04 | 0.25 | 0.25 | {'200': 28} |
| person_display_values | 28 | 0.05 | 3.18 | 4.41 | {'200': 26, '429': 2} |
| person_trend_8h | 28 | 0.02 | 3.35 | 3.81 | {'200': 28} |
| method reads | 36 | 16.05 | 19.57 | 19.73 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 31.2 | 8.8 | 0 | 224 |
| compute-gateway | 10.2 | 0.9 | 0 | 61 |
| dashcraft | 33.6 | 2.8 | 0 | 96 |
| doccraft | 1.0 | 0.3 | 0 | 86 |
| histcraft | 144.4 | 47.9 | 17 | 490 |
| histcraft-collector | 70.1 | 8.1 | 0 | 96 |
| histcraft-db | 10.8 | 4.5 | 0 | 103 |
| histcraft-gateway | 2.9 | 0.5 | 0 | 131 |
| installer | 55.0 | 8.7 | 0 | 20 |
| linkcraft | 122.2 | 17.9 | 4 | 470 |
| linkcraft-executor | 219.3 | 25.2 | 9 | 335 |
| llm-egress | 25.2 | 1.9 | 0 | 17 |
| modelcraft | 30.4 | 2.6 | 0 | 165 |
| modelcraft-executor | 0.5 | 0.4 | 0 | 197 |
| processcraft | 61.5 | 14.8 | 0 | 577 |
| proxy | 8.2 | 1.8 | 0 | 30 |
| simcraft | 44.3 | 19.0 | 0 | 306 |
