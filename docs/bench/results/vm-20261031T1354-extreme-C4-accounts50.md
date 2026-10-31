# Extreme load C4 accounts50 (2026-10-31T13:54Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 50 people, rounds on, 167 signals x 24 h, raw. Run 98 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 19.849 | ok |
| Analytics checks | 29.84 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 717 | 0.22 | 2.03 | 4.71 | {'200': 717} |
| person_display_values | 717 | 0.12 | 0.4 | 0.74 | {'200': 717} |
| person_trend_8h | 717 | 0.07 | 0.26 | 0.63 | {'200': 717} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 64.3 | 12.1 | 0 | 198 |
| compute-gateway | 11.9 | 2.1 | 0 | 46 |
| dashcraft | 45.8 | 2.2 | 0 | 104 |
| doccraft | 24.2 | 1.6 | 0 | 99 |
| histcraft | 175.8 | 49.9 | 4 | 494 |
| histcraft-collector | 86.1 | 13.5 | 0 | 205 |
| histcraft-db | 23.1 | 7.5 | 0 | 142 |
| histcraft-gateway | 0.6 | 0.4 | 0 | 33 |
| installer | 50.5 | 6.4 | 0 | 102 |
| linkcraft | 132.0 | 62.2 | 9 | 903 |
| linkcraft-executor | 164.2 | 19.9 | 4 | 390 |
| llm-egress | 44.0 | 2.1 | 0 | 34 |
| modelcraft | 47.2 | 2.8 | 0 | 134 |
| modelcraft-executor | 10.0 | 1.3 | 0 | 19 |
| processcraft | 233.6 | 66.8 | 22 | 564 |
| proxy | 17.7 | 8.7 | 0 | 21 |
| simcraft | 98.1 | 31.2 | 0 | 299 |
