# Read bench (Saturday 2026-10-31, plan items A1 to A3)

Where the time of an Analytics round's read goes, and what the binary answer, the block frame and incremental reads change. It needs a PostgreSQL, the branch's packages in a venv, and no Docker suite.

- `seed.py`: N points x D days through the Historian's real write path and compressor (`gen.py`). `--thin 10` gives demo density, about 1,500 values per point per day; without it you get about 15,000.
- `serve.py`: the Historian API over that database, with a FakePlantCraft for the token.
- `breakdown.py`: one read stage by stage, in one process. `round.py`: a real `MonitorService.run_once`.
- `e2e.py`, `scale.py`, `incr.py`: reads over HTTP, many rounds at once, and incremental against whole reads.
- `layouts.py`: PostgreSQL layouts keyed by tag (A3).
- `vm-run.sh`: all of it inside a Linux VM, with PostgreSQL 17 in Docker.

The paths in the scripts point at `/home/user/bench`; `vm-run.sh` rewrites them.
