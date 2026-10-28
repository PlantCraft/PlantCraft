# Oracles

Cases with a known answer, run against PlantCraft Analytics's methods through `FakePlantCraft`, so they
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
| `test_isdb_oracle.py` | `stiction_screening` against those labels; skipped while the data or labels are absent |

Run them with `pytest -q tests/oracles -rs` (they also run in `pytest -q`).
