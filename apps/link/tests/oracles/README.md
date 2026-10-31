# Oracles

Cases with a known answer, run against PlantCraft Analytics' methods through `FakePlantCraft`, so they
take the same PlantCraft API v1 path as production. Pass counts are floors in
`tests/floors.toml` (`[oracles]`) that only rise; a case the methods get wrong is recorded as a
strict expected failure tied to its gap in `docs/gaps.md`, never tuned away.

| File | What |
|---|---|
| `simulator.py` | PlantCraft Simulator's loop dynamics, copied (see its header) |
| `simulator_cases.py` | 10 loops with a known fault and the verdict each must get |
| `test_simulator_oracle.py` | one round over them; pass count >= `simulator_cases` |
| `fetch_isdb.py` | downloads the International Stiction Database at a pinned sha256 into `oracles/isdb/` (gitignored) and converts it to CSV (needs SciPy at fetch time) |
| `isdb_labels.toml` | published stiction labels, transcribed from Jelali and Huang (2010) with the table cited; empty until the data is pinned (G3) |
| `fetch_skab.py` | downloads the Skoltech Anomaly Benchmark (GPL-3.0) at a pinned commit, each file checked by sha256, into `oracles/skab/` (gitignored); the tests on main run it before `make ci` |
| `test_skab_oracle.py` | the Deviation (T²) block on SKAB's 34 labelled pump experiments: F1 and quiet share per sample and per 60-sample run, each >= its floor; skipped while the data is absent |
| `test_isdb_oracle.py` | `stiction_screening` against those labels; skipped while the data or labels are absent |

Run them with `pytest -q tests/oracles -rs` (they also run in `pytest -q`).
