# Extreme load C2 B2-LINKCRAFT_EXECUTOR-2-r1 (2026-10-31T11:10Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 57 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 26.255 | ok |
| Analytics checks | 30.46 | ok |
| 9 methods (slowest) | 17.8 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 30 | 0.06 | 0.15 | 0.2 | {'200': 30} |
| person_display_values | 30 | 0.07 | 3.65 | 4.48 | {'200': 29, '429': 1} |
| person_trend_8h | 30 | 0.03 | 3.83 | 5.24 | {'200': 30} |
| method reads | 36 | 15.66 | 17.76 | 17.78 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 33.2 | 7.0 | 0 | 187 |
| compute-gateway | 11.5 | 1.7 | 0 | 48 |
| dashcraft | 31.4 | 3.6 | 0 | 114 |
| doccraft | 0.9 | 0.3 | 0 | 87 |
| histcraft | 128.0 | 40.2 | 17 | 450 |
| histcraft-collector | 102.3 | 14.4 | 4 | 158 |
| histcraft-db | 25.4 | 4.5 | 0 | 133 |
| histcraft-gateway | 0.7 | 0.4 | 0 | 131 |
| installer | 46.7 | 9.1 | 0 | 40 |
| linkcraft | 37.7 | 8.6 | 0 | 546 |
| linkcraft-executor | 196.6 | 33.3 | 13 | 322 |
| llm-egress | 32.4 | 2.3 | 0 | 17 |
| modelcraft | 47.9 | 6.6 | 0 | 180 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 202 |
| processcraft | 39.5 | 11.2 | 0 | 567 |
| proxy | 9.6 | 2.2 | 0 | 29 |
| simcraft | 64.1 | 27.1 | 0 | 300 |
