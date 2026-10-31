# Extreme load C2 base (2026-10-30T15:19Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 57 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 29.879 | ok |
| Analytics checks | 33.75 | ok |
| 9 methods (slowest) | 26.1 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 27 | 0.04 | 0.08 | 0.11 | {'200': 27} |
| person_display_values | 27 | 0.05 | 7.25 | 8.3 | {'200': 25, '429': 2} |
| person_trend_8h | 27 | 0.02 | 3.44 | 4.26 | {'200': 27} |
| method reads | 36 | 24.3 | 25.99 | 26.04 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 35.4 | 5.4 | 0 | 175 |
| compute-gateway | 11.6 | 1.6 | 0 | 51 |
| dashcraft | 28.9 | 4.3 | 0 | 107 |
| doccraft | 20.2 | 1.6 | 0 | 120 |
| histcraft | 129.5 | 52.8 | 25 | 399 |
| histcraft-collector | 87.0 | 9.2 | 0 | 149 |
| histcraft-db | 10.1 | 2.4 | 0 | 128 |
| histcraft-gateway | 1.5 | 0.3 | 0 | 56 |
| installer | 36.9 | 6.4 | 0 | 31 |
| linkcraft | 50.6 | 11.1 | 0 | 620 |
| linkcraft-executor | 220.3 | 22.5 | 4 | 367 |
| llm-egress | 31.5 | 2.2 | 0 | 33 |
| modelcraft | 33.1 | 2.6 | 0 | 136 |
| modelcraft-executor | 4.8 | 1.0 | 0 | 186 |
| processcraft | 36.5 | 7.2 | 0 | 518 |
| proxy | 8.0 | 1.7 | 0 | 21 |
| simcraft | 16.4 | 9.1 | 0 | 229 |
