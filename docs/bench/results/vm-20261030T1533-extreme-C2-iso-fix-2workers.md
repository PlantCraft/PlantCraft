# Extreme load C2 iso-fix-2workers (2026-10-30T15:33Z)

Machine: vm, 4 CPUs 16872808448 x86_64. Load: 9 methods besides the rounds, 3 people, rounds on, 167 signals x 24 h, raw. Run 48 s.

| Work | Seconds | Status |
|---|---|---|
| Analytics round | 10.052 | ok |
| Analytics checks | 13.09 | ok |
| 9 methods (slowest) | 6.5 | {'200': 36} |

| Caller | Calls | p50 s | p95 s | max s | Statuses |
|---|---|---|---|---|---|
| person_analytics_overview | 28 | 0.07 | 0.11 | 0.15 | {'200': 28} |
| person_display_values | 28 | 0.06 | 0.35 | 0.49 | {'200': 28} |
| person_trend_8h | 28 | 0.02 | 0.68 | 1.05 | {'200': 28} |
| method reads | 36 | 5.06 | 6.41 | 6.46 | {'200': 36} |

| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |
|---|---|---|---|---|
| alarmcraft | 50.3 | 9.9 | 0 | 185 |
| compute-gateway | 17.3 | 3.0 | 0 | 51 |
| dashcraft | 5.0 | 0.6 | 0 | 106 |
| doccraft | 30.5 | 3.0 | 0 | 117 |
| histcraft | 142.6 | 25.7 | 4 | 526 |
| histcraft-collector | 72.8 | 11.4 | 0 | 211 |
| histcraft-db | 23.0 | 4.1 | 0 | 170 |
| histcraft-gateway | 0.5 | 0.3 | 0 | 56 |
| installer | 56.0 | 6.7 | 0 | 37 |
| linkcraft | 81.6 | 13.7 | 0 | 672 |
| linkcraft-executor | 76.0 | 11.5 | 0 | 394 |
| llm-egress | 21.7 | 1.8 | 0 | 17 |
| modelcraft | 38.0 | 5.8 | 0 | 157 |
| modelcraft-executor | 4.9 | 0.8 | 0 | 186 |
| processcraft | 32.8 | 7.9 | 0 | 530 |
| proxy | 2.5 | 0.6 | 0 | 21 |
| simcraft | 91.6 | 28.8 | 0 | 307 |
