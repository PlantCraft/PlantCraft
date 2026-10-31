# Extreme load C2 hunt-cache32-r2 (2026-10-31T14:05Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 57 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 26.003 | ok |
| Analytics checks | 21.07 | ok |
| 9 methods (slowest) | 15.6 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 33 | 0.08 | 0.27 | 0.36 | {'200': 33} |
| person_display_values | 33 | 0.09 | 1.37 | 1.81 | {'429': 2, '200': 31} |
| person_trend_8h | 33 | 0.04 | 1.53 | 2.37 | {'200': 33} |
| method reads | 36 | 10.3 | 15.55 | 15.62 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 49.0 | 6.7 | 0 | 226 |
| compute-gateway | 11.9 | 1.9 | 0 | 56 |
| dashcraft | 0.3 | 0.2 | 0 | 99 |
| doccraft | 0.3 | 0.2 | 0 | 90 |
| histcraft | 194.8 | 48.4 | 13 | 822 |
| histcraft-collector | 88.7 | 12.1 | 0 | 144 |
| histcraft-db | 42.1 | 6.8 | 0 | 152 |
| histcraft-gateway | 2.6 | 0.5 | 0 | 32 |
| installer | 50.9 | 5.3 | 0 | 38 |
| linkcraft | 102.9 | 18.8 | 4 | 709 |
| linkcraft-executor | 160.8 | 27.9 | 9 | 396 |
| llm-egress | 36.0 | 3.3 | 0 | 33 |
| modelcraft | 0.5 | 0.3 | 0 | 136 |
| modelcraft-executor | 0.7 | 0.5 | 0 | 10 |
| processcraft | 37.3 | 12.2 | 0 | 573 |
| proxy | 11.9 | 2.8 | 0 | 19 |
| simcraft | 100.5 | 34.9 | 4 | 350 |
