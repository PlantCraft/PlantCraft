# People at once: Macs-Mac-mini, 2026-10-27 13:48 UTC

Machine: {'host': 'Macs-Mac-mini', 'system': 'Darwin 27.0.0 arm64', 'cpus': 12, 'memory_gib': 48.0, 'docker': '12 CPUs 16747556864 aarch64'}. Think time [5.0, 15.0] s; 119 pages, 18.5 calls each on average (71 recorded calls left out: not on this install).

| People | Pages/s | Calls/s | Page p50 | Page p95 | Page max | Call p95 | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 0.14 | 3.3 | 18.971 s | 61.535 s | 62.226 s | 8.002 s | 3.06 % |
| 50 | 0.28 | 5.8 | 60.06 s | 102.621 s | 153.609 s | 31.201 s | 14.98 % |

Heavy questions after 30 % of pages (p50 / p95 / max):

| People | dashboard 30d | dashboard 7d | history 1d raw | history 30d | history 90d | report 30d | trend 30d | trend 7d | trend 90d |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | - | 8.848 / 16.404 / 16.404 s (2) | - | - | 0.016 / 0.049 / 0.049 s (3) | 60.013 / 60.185 / 60.185 s (10) | 0.762 / 0.762 / 0.762 s (1) | - | - |
| 50 | 15.251 / 120.02 / 120.02 s (4) | 60.018 / 180.024 / 180.024 s (5) | 0.774 / 2.027 / 2.027 s (3) | 0.015 / 0.071 / 0.071 s (4) | 0.061 / 1.793 / 1.793 s (3) | 62.008 / 190.994 / 190.994 s (12) | 0.135 / 60.01 / 60.01 s (5) | 0.044 / 60.006 / 60.006 s (4) | 0.872 / 60.006 / 60.006 s (3) |

Where the time goes with 50 people (routes with most seconds):

| Route | Calls | Seconds | p95 |
|---|---:|---:|---:|
| `GET /api/notebooks` | 111 | 1228.9 | 32.059 s |
| `GET /api/assistant` | 122 | 1228.3 | 30.819 s |
| `GET /link/api/meta` | 42 | 929.3 | 56.386 s |
| `GET /link/api/me` | 41 | 864.4 | 55.303 s |
| `GET /api/<id>/inbox` | 129 | 436.0 | 36.048 s |
| `GET /api/desk/team-page` | 115 | 311.9 | 35.504 s |
| `GET /api/session` | 119 | 310.6 | 27.421 s |
| `GET /api/me/preferences` | 114 | 287.4 | 30.792 s |
| `GET /link/api/methods` | 6 | 234.4 | 51.795 s |
| `GET /link/api/widgets` | 6 | 207.4 | 56.56 s |
| `GET /api/home` | 107 | 195.0 | 1.92 s |
| `GET /link/api/queue` | 3 | 173.5 | 58.995 s |

| Container | Peak CPU | Peak memory |
|---|---:|---:|
| alarmcraft | 45 % | 438 MiB |
| compute-gateway | 6 % | 77 MiB |
| dashcraft | 17 % | 214 MiB |
| doccraft | 9 % | 587 MiB |
| histcraft | 105 % | 1900 MiB |
| histcraft-collector | 89 % | 312 MiB |
| histcraft-db | 27 % | 710 MiB |
| histcraft-gateway | 1 % | 43 MiB |
| installer | 20 % | 93 MiB |
| linkcraft | 229 % | 3978 MiB |
| linkcraft-executor | 5 % | 23 MiB |
| llm-egress | 19 % | 13 MiB |
| modelcraft | 14 % | 174 MiB |
| modelcraft-executor | 2 % | 13 MiB |
| plantcraft | 65 % | 400 MiB |
| processcraft | 199 % | 2906 MiB |
| proxy | 3 % | 65 MiB |
