# Extreme load C2 B2-LINKCRAFT_EXECUTOR-1-r1 (2026-10-31T11:09Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 60 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 30.295 | ok |
| Analytics checks | 33.3 | ok |
| 9 methods (slowest) | 16.6 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 33 | 0.05 | 0.15 | 0.2 | {'200': 33} |
| person_display_values | 33 | 0.06 | 2.49 | 2.63 | {'429': 3, '200': 30} |
| person_trend_8h | 33 | 0.03 | 1.53 | 1.71 | {'200': 33} |
| method reads | 36 | 13.9 | 16.46 | 16.51 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 34.1 | 5.9 | 0 | 184 |
| compute-gateway | 4.9 | 0.9 | 0 | 49 |
| dashcraft | 39.5 | 5.1 | 0 | 101 |
| doccraft | 0.2 | 0.2 | 0 | 86 |
| histcraft | 123.5 | 37.9 | 17 | 400 |
| histcraft-collector | 14.3 | 2.8 | 0 | 96 |
| histcraft-db | 33.4 | 4.2 | 0 | 132 |
| histcraft-gateway | 0.5 | 0.3 | 0 | 131 |
| installer | 39.8 | 5.4 | 0 | 36 |
| linkcraft | 44.7 | 10.1 | 0 | 530 |
| linkcraft-executor | 100.8 | 24.4 | 12 | 335 |
| llm-egress | 50.9 | 3.4 | 0 | 34 |
| modelcraft | 34.7 | 4.7 | 0 | 161 |
| modelcraft-executor | 2.8 | 0.7 | 0 | 202 |
| processcraft | 49.6 | 12.1 | 0 | 556 |
| proxy | 10.2 | 1.9 | 0 | 29 |
| simcraft | 74.8 | 24.7 | 0 | 292 |
