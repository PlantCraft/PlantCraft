# Extreme load C4 accounts50-kept2 (2026-10-31T14:05Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 50 people, rounds on, 167 signals x 24 h, raw. Run 119 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 24.871 | ok |
| Analytics checks | 32.95 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 829 | 0.03 | 0.51 | 1.56 | {'200': 829} |
| person_display_values | 829 | 0.29 | 0.94 | 1.74 | {'200': 829} |
| person_trend_8h | 829 | 0.14 | 0.64 | 1.7 | {'200': 829} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 54.5 | 10.9 | 0 | 185 |
| compute-gateway | 14.0 | 1.6 | 0 | 45 |
| dashcraft | 49.8 | 3.0 | 0 | 107 |
| doccraft | 30.1 | 2.5 | 0 | 104 |
| histcraft | 157.0 | 52.5 | 13 | 549 |
| histcraft-collector | 61.9 | 10.7 | 0 | 210 |
| histcraft-db | 18.1 | 8.8 | 0 | 163 |
| histcraft-gateway | 4.0 | 0.7 | 0 | 33 |
| installer | 52.5 | 6.6 | 0 | 110 |
| linkcraft | 72.5 | 21.7 | 0 | 694 |
| linkcraft-executor | 114.4 | 14.1 | 4 | 404 |
| llm-egress | 46.7 | 2.1 | 0 | 34 |
| modelcraft | 50.6 | 2.9 | 0 | 130 |
| modelcraft-executor | 0.7 | 0.5 | 0 | 19 |
| processcraft | 127.1 | 55.4 | 22 | 561 |
| proxy | 18.3 | 8.8 | 0 | 22 |
| simcraft | 106.8 | 37.5 | 9 | 348 |
