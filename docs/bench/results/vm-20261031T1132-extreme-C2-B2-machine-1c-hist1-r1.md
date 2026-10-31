# Extreme load C2 B2-machine-1c-hist1-r1 (2026-10-31T11:32Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 162 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 96.795 | ok |
| Analytics checks | 127.01 | ok |
| 9 methods (slowest) | 32.3 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 72 | 0.22 | 0.9 | 1.37 | {'200': 72} |
| person_display_values | 72 | 0.23 | 2.12 | 9.68 | {'429': 4, '200': 68} |
| person_trend_8h | 72 | 0.1 | 1.47 | 19.17 | {'200': 72} |
| method reads | 36 | 31.35 | 32.17 | 32.23 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 32.9 | 6.3 | 0 | 239 |
| compute-gateway | 12.2 | 1.4 | 0 | 69 |
| dashcraft | 36.4 | 2.9 | 0 | 108 |
| doccraft | 14.2 | 0.8 | 0 | 96 |
| histcraft | 62.3 | 14.8 | 0 | 568 |
| histcraft-collector | 40.4 | 7.7 | 0 | 160 |
| histcraft-db | 13.0 | 1.9 | 0 | 111 |
| histcraft-gateway | 3.7 | 0.4 | 0 | 130 |
| installer | 47.3 | 5.7 | 0 | 44 |
| linkcraft | 29.9 | 8.0 | 0 | 468 |
| linkcraft-executor | 47.0 | 12.4 | 0 | 310 |
| llm-egress | 29.7 | 2.0 | 0 | 32 |
| modelcraft | 25.1 | 2.3 | 0 | 176 |
| modelcraft-executor | 1.2 | 0.4 | 0 | 197 |
| processcraft | 31.3 | 8.3 | 0 | 582 |
| proxy | 7.8 | 0.9 | 0 | 30 |
| simcraft | 63.6 | 20.5 | 0 | 319 |
