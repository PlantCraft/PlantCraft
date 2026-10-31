# Extreme load C2 B0-defaults (2026-10-31T10:55Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 10 people, rounds on, 167 signals x 24 h, raw. Run 55 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics checks | 23.55 | ok |
| Analytics round | 30.51 | ok |
| 9 methods (slowest) | 15.6 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 97 | 0.07 | 0.68 | 0.79 | {'200': 97} |
| person_display_values | 97 | 0.07 | 0.67 | 5.93 | {'200': 79, '429': 18} |
| person_trend_8h | 97 | 0.03 | 5.51 | 6.37 | {'200': 97} |
| method reads | 36 | 13.64 | 15.55 | 15.56 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 35.2 | 6.3 | 0 | 181 |
| compute-gateway | 11.4 | 2.4 | 0 | 57 |
| dashcraft | 32.1 | 5.0 | 0 | 119 |
| doccraft | 0.3 | 0.2 | 0 | 82 |
| histcraft | 131.3 | 43.8 | 13 | 351 |
| histcraft-collector | 4.9 | 1.8 | 0 | 94 |
| histcraft-db | 19.1 | 5.5 | 0 | 98 |
| histcraft-gateway | 0.4 | 0.3 | 0 | 132 |
| installer | 30.8 | 3.7 | 0 | 30 |
| linkcraft | 78.1 | 17.6 | 0 | 447 |
| linkcraft-executor | 217.7 | 32.3 | 9 | 326 |
| llm-egress | 12.9 | 1.0 | 0 | 17 |
| modelcraft | 35.0 | 4.1 | 0 | 149 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 203 |
| processcraft | 54.1 | 15.7 | 0 | 623 |
| proxy | 18.0 | 3.9 | 0 | 28 |
| simcraft | 102.1 | 33.1 | 8 | 261 |
