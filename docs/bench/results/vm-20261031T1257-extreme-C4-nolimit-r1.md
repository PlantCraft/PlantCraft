# Extreme load C4 nolimit-r1 (2026-10-31T12:57Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 0 methods besides the rounds, 20 people, rounds on, 167 signals x 24 h, raw. Run 58 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 11.178 | ok |
| Analytics checks | 18.06 | ok |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 220 | 0.17 | 0.66 | 1.15 | {'200': 220} |
| person_display_values | 220 | 0.07 | 0.26 | 0.39 | {'429': 100, '200': 120} |
| person_trend_8h | 220 | 0.05 | 0.24 | 0.37 | {'200': 220} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 47.4 | 10.4 | 0 | 228 |
| compute-gateway | 9.5 | 1.9 | 0 | 47 |
| dashcraft | 14.9 | 1.3 | 0 | 116 |
| doccraft | 32.9 | 4.9 | 0 | 109 |
| histcraft | 197.2 | 37.6 | 4 | 338 |
| histcraft-collector | 90.0 | 14.4 | 0 | 280 |
| histcraft-db | 27.6 | 6.1 | 0 | 130 |
| histcraft-gateway | 2.5 | 0.5 | 0 | 33 |
| installer | 50.3 | 6.1 | 0 | 104 |
| linkcraft | 91.6 | 29.8 | 0 | 672 |
| linkcraft-executor | 109.2 | 23.0 | 9 | 392 |
| llm-egress | 39.7 | 3.8 | 0 | 34 |
| modelcraft | 35.4 | 4.9 | 0 | 142 |
| modelcraft-executor | 0.6 | 0.5 | 0 | 20 |
| processcraft | 70.8 | 19.0 | 0 | 486 |
| proxy | 11.1 | 3.7 | 0 | 19 |
| simcraft | 84.2 | 32.0 | 0 | 308 |
