# Extreme load C2 iso-fix (2026-10-30T15:26Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 45 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 16.097 | ok |
| Analytics checks | 18.19 | ok |
| 9 methods (slowest) | 10.3 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 25 | 0.05 | 0.17 | 0.23 | {'200': 25} |
| person_display_values | 25 | 0.05 | 1.81 | 2.16 | {'200': 24, '429': 1} |
| person_trend_8h | 25 | 0.02 | 1.55 | 1.69 | {'200': 25} |
| method reads | 36 | 8.02 | 10.2 | 10.21 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 36.8 | 5.8 | 0 | 175 |
| compute-gateway | 18.4 | 3.1 | 0 | 51 |
| dashcraft | 33.6 | 3.2 | 0 | 109 |
| doccraft | 0.2 | 0.2 | 0 | 111 |
| histcraft | 156.0 | 36.9 | 8 | 345 |
| histcraft-collector | 79.2 | 9.0 | 0 | 176 |
| histcraft-db | 23.3 | 6.2 | 0 | 124 |
| histcraft-gateway | 3.2 | 0.5 | 0 | 56 |
| installer | 45.7 | 9.5 | 0 | 33 |
| linkcraft | 86.7 | 14.3 | 0 | 637 |
| linkcraft-executor | 165.7 | 22.2 | 4 | 378 |
| llm-egress | 48.6 | 4.4 | 0 | 33 |
| modelcraft | 0.5 | 0.2 | 0 | 125 |
| modelcraft-executor | 0.5 | 0.4 | 0 | 186 |
| processcraft | 49.8 | 20.1 | 0 | 530 |
| proxy | 10.1 | 2.0 | 0 | 20 |
| simcraft | 16.5 | 12.8 | 0 | 287 |
