# Extreme load C2 B4-two-cores-priority-r2 (2026-10-31T13:25Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 84 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics checks | 48.16 | ok |
| Analytics round | 57.451 | ok |
| 9 methods (slowest) | 30.4 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 39 | 0.16 | 1.63 | 1.86 | {'200': 39} |
| person_display_values | 39 | 0.07 | 5.54 | 5.54 | {'200': 37, '429': 2} |
| person_trend_8h | 39 | 0.03 | 4.91 | 6.29 | {'200': 39} |
| method reads | 36 | 25.03 | 30.27 | 30.33 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 48.4 | 7.8 | 0 | 184 |
| compute-gateway | 9.3 | 1.6 | 0 | 48 |
| dashcraft | 35.9 | 3.5 | 0 | 93 |
| doccraft | 27.4 | 2.7 | 0 | 91 |
| histcraft | 111.5 | 40.7 | 26 | 636 |
| histcraft-collector | 59.4 | 7.8 | 0 | 158 |
| histcraft-db | 31.7 | 4.9 | 0 | 127 |
| histcraft-gateway | 2.1 | 0.4 | 0 | 33 |
| installer | 49.9 | 5.6 | 0 | 36 |
| linkcraft | 99.4 | 13.8 | 4 | 658 |
| linkcraft-executor | 72.4 | 17.7 | 0 | 354 |
| llm-egress | 48.4 | 2.4 | 0 | 35 |
| modelcraft | 45.6 | 5.9 | 0 | 137 |
| modelcraft-executor | 5.8 | 0.7 | 0 | 9 |
| processcraft | 38.9 | 10.1 | 0 | 545 |
| proxy | 8.2 | 1.9 | 0 | 19 |
| simcraft | 53.9 | 23.2 | 0 | 322 |
