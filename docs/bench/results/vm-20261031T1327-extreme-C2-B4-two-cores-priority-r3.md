# Extreme load C2 B4-two-cores-priority-r3 (2026-10-31T13:27Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 82 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics checks | 52.01 | ok |
| Analytics round | 56.129 | ok |
| 9 methods (slowest) | 32.5 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 37 | 0.13 | 0.56 | 0.57 | {'200': 37} |
| person_display_values | 37 | 0.07 | 5.15 | 9.45 | {'200': 37} |
| person_trend_8h | 37 | 0.03 | 3.84 | 10.99 | {'200': 37} |
| method reads | 36 | 24.0 | 31.98 | 32.51 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 51.9 | 11.9 | 0 | 197 |
| compute-gateway | 13.7 | 2.1 | 0 | 47 |
| dashcraft | 39.9 | 2.8 | 0 | 94 |
| doccraft | 12.7 | 1.2 | 0 | 101 |
| histcraft | 110.4 | 48.7 | 21 | 604 |
| histcraft-collector | 94.6 | 9.0 | 0 | 156 |
| histcraft-db | 13.8 | 3.6 | 0 | 130 |
| histcraft-gateway | 0.8 | 0.3 | 0 | 32 |
| installer | 29.8 | 5.3 | 0 | 31 |
| linkcraft | 66.8 | 14.0 | 0 | 658 |
| linkcraft-executor | 100.0 | 17.0 | 8 | 367 |
| llm-egress | 11.7 | 0.9 | 0 | 28 |
| modelcraft | 0.5 | 0.3 | 0 | 135 |
| modelcraft-executor | 5.8 | 0.7 | 0 | 9 |
| processcraft | 42.8 | 11.1 | 0 | 552 |
| proxy | 19.0 | 2.5 | 0 | 19 |
| simcraft | 76.6 | 24.3 | 0 | 341 |
