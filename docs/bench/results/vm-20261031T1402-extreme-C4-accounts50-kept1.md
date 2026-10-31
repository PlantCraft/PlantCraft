# Extreme load C4 accounts50-kept1 (2026-10-31T14:02Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 50 people, rounds on, 167 signals x 24 h, raw. Run 92 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 15.719 | ok |
| Analytics checks | 23.7 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 691 | 0.02 | 0.15 | 0.63 | {'200': 691} |
| person_display_values | 691 | 0.12 | 0.6 | 1.04 | {'200': 691} |
| person_trend_8h | 691 | 0.07 | 0.42 | 0.85 | {'200': 691} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 55.5 | 7.2 | 0 | 185 |
| compute-gateway | 19.5 | 3.8 | 0 | 52 |
| dashcraft | 41.6 | 4.2 | 0 | 117 |
| doccraft | 26.2 | 1.4 | 0 | 102 |
| histcraft | 152.0 | 57.0 | 17 | 512 |
| histcraft-collector | 99.4 | 13.9 | 4 | 222 |
| histcraft-db | 16.5 | 8.6 | 0 | 151 |
| histcraft-gateway | 3.9 | 0.8 | 0 | 33 |
| installer | 54.5 | 8.4 | 0 | 112 |
| linkcraft | 107.3 | 21.3 | 4 | 569 |
| linkcraft-executor | 218.7 | 31.1 | 9 | 399 |
| llm-egress | 25.6 | 2.3 | 0 | 27 |
| modelcraft | 29.5 | 3.0 | 0 | 138 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 19 |
| processcraft | 172.4 | 64.0 | 17 | 505 |
| proxy | 17.2 | 8.7 | 0 | 20 |
| simcraft | 54.9 | 24.8 | 0 | 314 |
