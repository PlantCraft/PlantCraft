# Extreme load C2 B2-PLANTCRAFT-4-r1 (2026-10-31T11:02Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 54 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 24.261 | ok |
| Analytics checks | 27.66 | ok |
| 9 methods (slowest) | 17.1 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.06 | 0.11 | 0.18 | {'200': 27} |
| person_display_values | 27 | 0.09 | 4.2 | 4.33 | {'200': 27} |
| person_trend_8h | 27 | 0.03 | 2.17 | 3.3 | {'200': 27} |
| method reads | 36 | 15.34 | 17.08 | 17.09 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 16.1 | 2.6 | 0 | 181 |
| compute-gateway | 15.6 | 2.3 | 0 | 50 |
| dashcraft | 0.3 | 0.2 | 0 | 98 |
| doccraft | 21.6 | 2.0 | 0 | 84 |
| histcraft | 124.2 | 49.7 | 13 | 414 |
| histcraft-collector | 120.2 | 18.8 | 4 | 148 |
| histcraft-db | 57.1 | 8.5 | 0 | 125 |
| histcraft-gateway | 0.6 | 0.4 | 0 | 132 |
| installer | 22.3 | 3.8 | 0 | 29 |
| linkcraft | 93.1 | 22.3 | 0 | 549 |
| linkcraft-executor | 158.7 | 28.3 | 9 | 377 |
| llm-egress | 0.0 | 0.0 | 0 | 17 |
| modelcraft | 0.3 | 0.3 | 0 | 169 |
| modelcraft-executor | 2.0 | 0.6 | 0 | 204 |
| processcraft | 48.0 | 11.0 | 0 | 536 |
| proxy | 14.0 | 2.5 | 0 | 29 |
| simcraft | 30.0 | 21.0 | 0 | 291 |
