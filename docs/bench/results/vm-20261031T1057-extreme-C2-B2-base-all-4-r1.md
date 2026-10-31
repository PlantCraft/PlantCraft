# Extreme load C2 B2-base-all-4-r1 (2026-10-31T10:57Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 51 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 24.333 | ok |
| Analytics checks | 24.97 | ok |
| 9 methods (slowest) | 16.7 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.06 | 0.17 | 0.26 | {'200': 27} |
| person_display_values | 27 | 0.07 | 3.99 | 4.09 | {'429': 2, '200': 25} |
| person_trend_8h | 27 | 0.04 | 1.19 | 1.61 | {'200': 27} |
| method reads | 36 | 15.45 | 16.45 | 16.66 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 59.0 | 7.1 | 0 | 181 |
| compute-gateway | 8.0 | 1.7 | 0 | 56 |
| dashcraft | 26.0 | 2.6 | 0 | 99 |
| doccraft | 43.0 | 6.2 | 0 | 92 |
| histcraft | 113.2 | 46.4 | 9 | 367 |
| histcraft-collector | 97.5 | 14.8 | 4 | 156 |
| histcraft-db | 25.8 | 4.4 | 0 | 90 |
| histcraft-gateway | 4.0 | 0.6 | 0 | 132 |
| installer | 46.8 | 6.3 | 0 | 28 |
| linkcraft | 32.6 | 9.0 | 0 | 480 |
| linkcraft-executor | 215.6 | 31.6 | 9 | 341 |
| llm-egress | 0.0 | 0.0 | 0 | 17 |
| modelcraft | 2.5 | 0.5 | 0 | 145 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 203 |
| processcraft | 36.5 | 10.1 | 0 | 606 |
| proxy | 20.9 | 3.6 | 0 | 28 |
| simcraft | 61.8 | 22.9 | 0 | 247 |
