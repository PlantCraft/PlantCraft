# Extreme load C2 B2-machine-4c-hist2-r1 (2026-10-31T11:55Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 45 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 22.585 | ok |
| Analytics checks | 10.25 | ok |
| 9 methods (slowest) | 18.0 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 24 | 0.06 | 0.13 | 0.16 | {'200': 24} |
| person_display_values | 24 | 0.06 | 2.23 | 5.4 | {'200': 24} |
| person_trend_8h | 24 | 0.02 | 1.94 | 2.21 | {'200': 24} |
| method reads | 36 | 15.44 | 17.86 | 17.99 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 37.3 | 6.5 | 0 | 223 |
| compute-gateway | 7.5 | 1.0 | 0 | 61 |
| dashcraft | 16.9 | 1.7 | 0 | 110 |
| doccraft | 0.3 | 0.2 | 0 | 88 |
| histcraft | 194.6 | 56.6 | 17 | 723 |
| histcraft-collector | 7.8 | 2.5 | 0 | 108 |
| histcraft-db | 14.4 | 4.1 | 0 | 105 |
| histcraft-gateway | 3.7 | 0.6 | 0 | 130 |
| installer | 42.5 | 5.9 | 0 | 27 |
| linkcraft | 35.6 | 11.0 | 0 | 692 |
| linkcraft-executor | 238.5 | 35.3 | 9 | 377 |
| llm-egress | 30.3 | 2.8 | 0 | 32 |
| modelcraft | 34.9 | 4.6 | 0 | 166 |
| modelcraft-executor | 4.9 | 0.9 | 0 | 195 |
| processcraft | 37.6 | 12.0 | 0 | 590 |
| proxy | 14.4 | 2.8 | 0 | 31 |
| simcraft | 99.4 | 32.6 | 8 | 324 |
