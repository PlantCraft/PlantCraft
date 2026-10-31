# Extreme load C4 nolimit-r3 (2026-10-31T13:14Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 20 people, rounds on, 167 signals x 24 h, raw. Run 58 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 12.026 | ok |
| Analytics checks | 17.81 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 224 | 0.11 | 0.88 | 1.27 | {'200': 224} |
| person_display_values | 224 | 0.07 | 0.22 | 0.72 | {'200': 120, '429': 104} |
| person_trend_8h | 224 | 0.03 | 0.2 | 0.51 | {'200': 224} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 55.5 | 7.4 | 0 | 230 |
| compute-gateway | 5.5 | 1.0 | 0 | 47 |
| dashcraft | 0.4 | 0.3 | 0 | 104 |
| doccraft | 0.3 | 0.2 | 0 | 96 |
| histcraft | 105.0 | 33.2 | 4 | 425 |
| histcraft-collector | 111.9 | 14.7 | 4 | 257 |
| histcraft-db | 27.1 | 6.4 | 0 | 190 |
| histcraft-gateway | 0.9 | 0.4 | 0 | 33 |
| installer | 68.3 | 10.8 | 0 | 126 |
| linkcraft | 106.5 | 43.5 | 4 | 789 |
| linkcraft-executor | 97.7 | 14.9 | 4 | 399 |
| llm-egress | 0.0 | 0.0 | 0 | 19 |
| modelcraft | 0.6 | 0.3 | 0 | 134 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 19 |
| processcraft | 51.6 | 21.6 | 0 | 511 |
| proxy | 13.6 | 4.8 | 0 | 19 |
| simcraft | 63.5 | 30.3 | 0 | 332 |
