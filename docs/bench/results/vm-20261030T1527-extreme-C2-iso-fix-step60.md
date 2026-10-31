# Extreme load C2 iso-fix-step60 (2026-10-30T15:27Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, means of 60 s. Run 41 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 12.818 | ok |
| Analytics checks | 14.63 | ok |
| 9 methods (slowest) | 10.9 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 24 | 0.05 | 0.06 | 0.08 | {'200': 24} |
| person_display_values | 24 | 0.05 | 0.87 | 0.93 | {'200': 23, '429': 1} |
| person_trend_8h | 24 | 0.02 | 2.98 | 3.06 | {'200': 24} |
| method reads | 36 | 10.32 | 10.84 | 10.86 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 0.2 | 0.2 | 0 | 175 |
| compute-gateway | 11.8 | 2.4 | 0 | 52 |
| dashcraft | 0.2 | 0.2 | 0 | 109 |
| doccraft | 0.2 | 0.2 | 0 | 111 |
| histcraft | 122.7 | 29.5 | 8 | 383 |
| histcraft-collector | 4.2 | 1.6 | 0 | 149 |
| histcraft-db | 5.2 | 1.9 | 0 | 128 |
| histcraft-gateway | 0.4 | 0.3 | 0 | 56 |
| installer | 43.4 | 6.8 | 0 | 32 |
| linkcraft | 87.0 | 13.9 | 0 | 655 |
| linkcraft-executor | 161.5 | 18.3 | 4 | 383 |
| llm-egress | 24.3 | 2.6 | 0 | 29 |
| modelcraft | 0.3 | 0.2 | 0 | 132 |
| modelcraft-executor | 0.5 | 0.4 | 0 | 186 |
| processcraft | 26.0 | 7.3 | 0 | 522 |
| proxy | 2.3 | 0.4 | 0 | 22 |
| simcraft | 87.7 | 24.3 | 0 | 286 |
