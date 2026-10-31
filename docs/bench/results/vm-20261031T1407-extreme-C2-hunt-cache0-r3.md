# Extreme load C2 hunt-cache0-r3 (2026-10-31T14:07Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 75 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 33.142 | ok |
| Analytics checks | 38.66 | ok |
| 9 methods (slowest) | 25.9 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 41 | 0.08 | 0.18 | 0.23 | {'200': 41} |
| person_display_values | 41 | 0.08 | 1.68 | 3.21 | {'429': 1, '200': 40} |
| person_trend_8h | 41 | 0.04 | 2.08 | 2.86 | {'200': 41} |
| method reads | 36 | 15.57 | 25.7 | 25.88 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 72.7 | 8.1 | 0 | 228 |
| compute-gateway | 11.3 | 1.3 | 0 | 54 |
| dashcraft | 39.6 | 4.8 | 0 | 103 |
| doccraft | 52.9 | 4.8 | 0 | 90 |
| histcraft | 203.4 | 56.5 | 22 | 803 |
| histcraft-collector | 111.2 | 12.1 | 4 | 153 |
| histcraft-db | 31.3 | 7.4 | 0 | 150 |
| histcraft-gateway | 0.8 | 0.4 | 0 | 32 |
| installer | 47.1 | 5.1 | 0 | 26 |
| linkcraft | 113.7 | 18.2 | 4 | 714 |
| linkcraft-executor | 149.4 | 17.5 | 4 | 405 |
| llm-egress | 7.9 | 0.4 | 0 | 27 |
| modelcraft | 33.3 | 2.3 | 0 | 134 |
| modelcraft-executor | 0.7 | 0.5 | 0 | 10 |
| processcraft | 61.7 | 12.3 | 0 | 588 |
| proxy | 13.1 | 2.4 | 0 | 19 |
| simcraft | 99.8 | 33.3 | 4 | 345 |
