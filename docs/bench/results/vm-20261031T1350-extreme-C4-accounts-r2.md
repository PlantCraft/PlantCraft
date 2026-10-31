# Extreme load C4 accounts-r2 (2026-10-31T13:50Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 20 people, rounds on, 167 signals x 24 h, raw. Run 67 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 15.277 | ok |
| Analytics checks | 20.85 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 235 | 0.09 | 0.27 | 0.59 | {'200': 235} |
| person_display_values | 235 | 0.08 | 0.22 | 0.76 | {'200': 235} |
| person_trend_8h | 235 | 0.03 | 0.14 | 0.58 | {'200': 235} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 52.7 | 7.7 | 0 | 186 |
| compute-gateway | 11.9 | 2.3 | 0 | 44 |
| dashcraft | 34.4 | 2.4 | 0 | 103 |
| doccraft | 32.8 | 2.3 | 0 | 86 |
| histcraft | 159.1 | 37.4 | 4 | 499 |
| histcraft-collector | 76.8 | 8.4 | 0 | 160 |
| histcraft-db | 16.5 | 5.3 | 0 | 120 |
| histcraft-gateway | 0.7 | 0.4 | 0 | 33 |
| installer | 40.5 | 4.1 | 0 | 95 |
| linkcraft | 102.6 | 35.2 | 4 | 732 |
| linkcraft-executor | 96.2 | 20.6 | 4 | 377 |
| llm-egress | 47.3 | 4.5 | 0 | 27 |
| modelcraft | 49.3 | 5.2 | 0 | 132 |
| modelcraft-executor | 8.7 | 1.1 | 0 | 19 |
| processcraft | 162.5 | 47.3 | 8 | 559 |
| proxy | 7.3 | 4.5 | 0 | 18 |
| simcraft | 74.5 | 25.8 | 0 | 271 |
