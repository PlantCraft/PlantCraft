# Extreme load C1 base (2026-10-30T15:17Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 3 people, rounds on, 214 signals x 24 h, raw. Run 35 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 6.963 | ok |
| Analytics checks | 11.29 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 21 | 0.04 | 0.11 | 0.15 | {'200': 21} |
| person_display_values | 21 | 0.04 | 0.2 | 0.22 | {'200': 20, '429': 1} |
| person_trend_8h | 21 | 0.01 | 0.08 | 0.11 | {'200': 21} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 2.2 | 0.4 | 0 | 173 |
| compute-gateway | 12.2 | 4.1 | 0 | 51 |
| dashcraft | 0.2 | 0.2 | 0 | 106 |
| doccraft | 0.3 | 0.2 | 0 | 108 |
| histcraft | 97.2 | 20.3 | 4 | 243 |
| histcraft-collector | 112.8 | 14.4 | 4 | 148 |
| histcraft-db | 11.1 | 3.4 | 0 | 110 |
| histcraft-gateway | 1.7 | 0.4 | 0 | 56 |
| installer | 23.4 | 3.9 | 0 | 37 |
| linkcraft | 62.0 | 12.6 | 0 | 546 |
| linkcraft-executor | 176.3 | 24.9 | 4 | 365 |
| llm-egress | 0.0 | 0.0 | 0 | 17 |
| modelcraft | 0.3 | 0.2 | 0 | 128 |
| modelcraft-executor | 5.2 | 0.9 | 0 | 186 |
| processcraft | 35.3 | 11.2 | 0 | 516 |
| proxy | 2.7 | 0.8 | 0 | 17 |
| simcraft | 89.7 | 24.8 | 0 | 244 |
