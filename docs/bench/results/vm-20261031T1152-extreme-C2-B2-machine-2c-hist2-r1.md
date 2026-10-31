# Extreme load C2 B2-machine-2c-hist2-r1 (2026-10-31T11:52Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 68 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 23.928 | ok |
| Analytics checks | 32.24 | ok |
| 9 methods (slowest) | 12.4 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 37 | 0.07 | 0.23 | 0.32 | {'200': 37} |
| person_display_values | 37 | 0.07 | 3.02 | 3.53 | {'429': 2, '200': 35} |
| person_trend_8h | 37 | 0.02 | 3.56 | 4.53 | {'200': 37} |
| method reads | 36 | 10.28 | 12.32 | 12.41 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 52.6 | 12.1 | 0 | 225 |
| compute-gateway | 2.4 | 0.6 | 0 | 61 |
| dashcraft | 21.9 | 1.6 | 0 | 98 |
| doccraft | 60.1 | 6.1 | 0 | 100 |
| histcraft | 187.6 | 33.4 | 9 | 628 |
| histcraft-collector | 103.7 | 14.6 | 4 | 160 |
| histcraft-db | 13.2 | 4.0 | 0 | 110 |
| histcraft-gateway | 3.5 | 0.5 | 0 | 130 |
| installer | 36.1 | 5.2 | 0 | 26 |
| linkcraft | 78.6 | 13.5 | 0 | 681 |
| linkcraft-executor | 144.2 | 21.6 | 4 | 352 |
| llm-egress | 49.4 | 3.1 | 0 | 34 |
| modelcraft | 3.3 | 0.5 | 0 | 171 |
| modelcraft-executor | 0.6 | 0.4 | 0 | 195 |
| processcraft | 19.9 | 7.8 | 0 | 575 |
| proxy | 12.3 | 2.3 | 0 | 30 |
| simcraft | 27.7 | 15.6 | 0 | 307 |
