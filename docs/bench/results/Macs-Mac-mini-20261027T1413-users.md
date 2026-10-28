# People at once: Macs-Mac-mini, 2026-10-27 14:13 UTC

Machine: {'host': 'Macs-Mac-mini', 'system': 'Darwin 27.0.0 arm64', 'cpus': 12, 'memory_gib': 48.0, 'docker': '12 CPUs 16747556864 aarch64'}. Think time [5.0, 15.0] s; 119 pages, 18.5 calls each on average (71 recorded calls left out: not on this install).

| People | Pages/s | Calls/s | Page p50 | Page p95 | Page max | Call p95 | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 0.63 | 12.8 | 0.304 s | 2.894 s | 9.724 s | 0.32 s | 0.16 % |
| 50 | 2.35 | 49.7 | 2.222 s | 16.032 s | 28.563 s | 2.405 s | 12.87 % |

Heavy questions after 30 % of pages (p50 / p95 / max):

| People | dashboard 30d | dashboard 7d | history 1d raw | history 30d | history 90d | report 30d | trend 30d | trend 7d | trend 90d |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | - | 0.203 / 0.79 / 0.79 s (6) | 0.016 / 0.183 / 0.183 s (5) | 0.087 / 0.159 / 0.159 s (2) | 0.014 / 0.044 / 0.044 s (3) | 1.304 / 5.509 / 5.509 s (10) | 0.064 / 0.064 / 0.064 s (1) | 0.253 / 0.253 / 0.253 s (1) | 0.079 / 0.101 / 0.101 s (4) |
| 50 | 0.544 / 19.31 / 19.31 s (17) | 0.178 / 7.939 / 17.575 s (21) | 0.015 / 2.021 / 2.021 s (9) | 0.015 / 4.206 / 4.206 s (14) | 0.015 / 1.13 / 1.13 s (12) | 3.966 / 11.585 / 14.809 s (42) | 0.101 / 8.614 / 11.646 s (24) | 0.096 / 0.983 / 0.983 s (10) | 0.082 / 8.002 / 8.002 s (11) |

Where the time goes with 50 people (routes with most seconds):

| Route | Calls | Seconds | p95 |
|---|---:|---:|---:|
| `GET /link/api/queue` | 486 | 1276.2 | 12.528 s |
| `GET /hist/api/queue` | 480 | 402.8 | 9.555 s |
| `GET /api/assistant` | 340 | 285.3 | 3.087 s |
| `GET /dash/api/reports/<id>/sections/by-loop` | 24 | 138.6 | 8.648 s |
| `GET /dash/api/reports/<id>/sections/by-problem` | 20 | 120.4 | 10.067 s |
| `GET /link/api/widgets/schedules` | 6 | 120.3 | 25.201 s |
| `GET /link/api/widgets/subject` | 6 | 111.7 | 25.533 s |
| `GET /link/api/overview` | 6 | 75.4 | 18.797 s |
| `GET /link/api/widgets/attention` | 9 | 55.8 | 10.832 s |
| `GET /link/api/methods` | 42 | 55.4 | 4.177 s |
| `GET /dash/api/dashboards/<id>/cards/table-up` | 19 | 49.0 | 19.061 s |
| `GET /link/api/widgets/results` | 6 | 46.2 | 10.831 s |

| Container | Peak CPU | Peak memory |
|---|---:|---:|
| alarmcraft | 104 % | 468 MiB |
| compute-gateway | 5 % | 81 MiB |
| dashcraft | 31 % | 171 MiB |
| doccraft | 4 % | 594 MiB |
| histcraft | 166 % | 732 MiB |
| histcraft-collector | 82 % | 317 MiB |
| histcraft-db | 37 % | 687 MiB |
| histcraft-gateway | 0 % | 39 MiB |
| installer | 20 % | 59 MiB |
| linkcraft | 219 % | 3054 MiB |
| linkcraft-executor | 6 % | 27 MiB |
| llm-egress | 20 % | 24 MiB |
| modelcraft | 18 % | 205 MiB |
| modelcraft-executor | 0 % | 14 MiB |
| plantcraft | 74 % | 229 MiB |
| processcraft | 295 % | 637 MiB |
| proxy | 9 % | 52 MiB |
