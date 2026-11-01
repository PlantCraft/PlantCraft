# PlantCraft Analytics spec

PlantCraft Analytics is an engine of monitoring algorithms: blocks with typed, described inputs and
outputs, wired into algorithms that run on a schedule over the plant's assets, publish an explained
verdict on the asset and write chosen outputs to the Historian. The five principles that govern it
are in `AGENTS.md` ("What PlantCraft Analytics is"); this spec follows them.

Category: signal data quality and control loop performance monitoring (CPM): judge every
signal's recorded data (gaps, stale, frozen, spiky, out-of-range, noisy, coarse, drifting), score
every loop of a plant from routine operating data, find the ones that need attention, say why
(tracking, oscillation, valve stiction, saturation, noise, manual operation, data quality) and
report it. PlantCraft Analytics is the former CPMCraft and DataCraft; DataCraft's
features and tests moved here. Tools studied
(research only): Control Station PlantESP, Honeywell Control Performance Analytics (formerly
Control Performance Monitor), Emerson DeltaV Insight / PlantTriage loop diagnostics, ABB Loop
Performance Manager, AspenTech Aspen Watch. Sources are public only (clean room, see AGENTS.md).

## Sources

| Source | Link | Read on |
|---|---|---|
| Bauer, Horch, Xie, Jelali, Thornhill (2016), The current state of control loop performance monitoring: a survey of application in industry | https://doi.org/10.1016/j.jprocont.2015.11.002 | 2026-10-19 |
| Harris (1989), Assessment of control loop performance | https://doi.org/10.1002/cjce.5450670519 | 2026-10-19 |
| Horch and Isaksson (1999), A modified index for control performance assessment | https://doi.org/10.1016/S0959-1524(99)00031-1 | 2026-10-19 |
| Thornhill and Hägglund (1997), Detection and diagnosis of oscillation in control loops | https://doi.org/10.1016/S0967-0661(97)00131-7 | 2026-10-19 |
| Thornhill, Huang, Zhang (2003), Detection of multiple oscillations in control loops, J. Process Control 13(1) 91-100 (regularity of the ACF zero crossings) | https://doi.org/10.1016/S0959-1524(02)00007-0 | 2026-10-19 |
| Choudhury, Thornhill, Shah (2005), Modelling valve stiction, Control Engineering Practice 13(5) 641-658 (stick band, then slip) | https://doi.org/10.1016/j.conengprac.2004.05.005 | 2026-10-19 |
| Choudhury, Shah, Thornhill (2006), Automatic detection and quantification of stiction in control valves | https://doi.org/10.1016/j.conengprac.2005.10.003 | 2026-10-19 |
| Jelali and Huang (2010), Detection and Diagnosis of Stiction in Control Loops (book; International Stiction Database) | https://doi.org/10.1007/978-1-84882-775-2 | 2026-10-19 |
| Book page with the database archive (`ISDB.zip`, "data sets used in the book", teaching and research use) | https://sites.ualberta.ca/~bhuang/Stiction-Book/ | 2026-10-19 (page read; archive not reachable from here) |
| Vendor product pages and public brochures of the tools above | links to be added (G21) | |

## Loop source

Where PlantCraft Analytics' loops come from (decided 2026-10-19):

1. **PlantCraft loop assets** (asset catalog, stage 2 of the asset model, 2026-10-19): every
   asset whose `type_path` contains `loop` (`LINKCRAFT_LOOP_ASSET_KIND`), so types derived from
   it (`cascade_loop`) count too; a PlantCraft without `type_path` is read by `kind`. Each
   round, and on `POST /api/loops/sync`, PlantCraft Analytics reads `GET /api/v1/assets` (one request, so
   parents resolve) and `GET /api/v1/asset-types` (required roles; optional) and writes the
   loops into **its own loop table** (`loops/store.py`, origin `processcraft`):
   - `id` → loop id, `name` → name, `attributes.description` → service, parent → area,
     grandparent → unit, `signals` roles `pv`, `sp`, `op`, `mode`, `secondary` → signal ids.
   - `attributes.loop_type` and `attributes.criticality` → the loop's starting algorithm,
     loop-type parameters and criticality weight (`docs/loop-types.md`); `action`,
     `controller`, `type_path` and `relations` are kept as the loop's asset record and shown.
   - A loop asset without a signal for a required role (`pv` and `op`: from the type
     definitions, or assumed when PlantCraft does not serve them) is an **incomplete
     record**: listed with the roles missing, never analysed, runs refused (409).
   - PlantCraft owns the name, signals and record (editing them here answers 409); PlantCraft Analytics
     owns the CPM settings (algorithm, criticality, enabled, method parameters). Algorithm and
     criticality follow the record until a person changes them here (`set_here`); from then a
     sync keeps them, and "Use the asset record" gives them back. The loop page says where
     each value came from.
   - An asset that disappears is disabled here (metadata `asset_missing`), never deleted, so its
     history stays.
2. **Loops defined in PlantCraft Analytics** (origin `user`, `POST /api/loops`) from PlantCraft v1 signal
   ids; every id is checked against `GET /api/v1/signals/{id}` with the person's token. They are
   edited and deleted here.

Why: the plant structure has one owner (PlantCraft), PlantCraft Analytics still works where the asset tree
is incomplete, and CPM settings never leak into the central app.

## Features

| Area | Feature in the target tool | Source | Ours | Test or oracle |
|---|---|---|---|---|
| Data | Read loop data from the plant historian | survey | done, through PlantCraft API v1 only | `tests/test_contract.py` |
| Data | Loops from the plant's asset model | survey | done (loop assets of the asset catalog with type, attributes, roles and relations; incomplete records listed) | `tests/test_rounds.py`, `tests/test_catalog_sync.py` |
| Algorithms | Assessment defaults from the loop type (flow, level, pressure, temperature, composition) | survey | done (`docs/loop-types.md`) | `tests/test_loop_types.py` |
| Data | Data quality screening before judging a loop (gaps, frozen, invalid values) | survey | done (loop data gate: `dq_availability`, `dq_value_integrity`, `dq_statistics`; and the signals' own verdicts) | `tests/test_data_quality.py`, `tests/test_suite.py` |
| Signals | Every signal judged on a schedule, with a verdict, a 0-100 quality and why (system algorithm Signal quality) | survey | done (8 checks `sq_*`: availability, freshness, frozen, spikes, range, noise, resolution, drift) | `tests/test_signal_checks.py`, `tests/test_signal_api.py`, `tests/oracles/test_signal_synthetic_oracle.py` |
| Signals | Per-signal page: chart with the events each check found, every check's result, 30-day history, own limits and check settings | survey | done | `tests/test_signal_api.py`, e2e |
| Signals | Verdicts shared with other apps (results on the signal and the asset, derived quality series) | survey | done (`linkcraft.signal_quality`, `app-linkcraft:<signal>.quality`) | `tests/test_signal_publish.py` |
| Reporting | Overview: results now and over the week; Results report (PDF) for any filter; dashboards in PlantCraft View | survey | done | `tests/test_signal_api.py`, `tests/test_results_api.py`, e2e |
| Data | Controller mode (auto/manual) from the DCS | survey | done: text modes (`AUTO`/`MAN`, API v1 `kind: text`) and numeric modes | `tests/test_rounds.py` |
| Diagnosis | Basic PV-SP error metrics (`error_metrics_basic`) | Harris 1989 | done | `tests/test_methods.py`, `tests/test_hostile_inputs.py` |
| Diagnosis | Operational interventions (`operational_interventions`) | survey | done | same |
| Diagnosis | Disturbance attenuation (`disturbance_attenuation`) | survey | done | same |
| Diagnosis | Time inside operating band (`operating_band_fraction`) | survey | done | same |
| Diagnosis | Sampling quality (`sampling_quality`) | survey | done | same |
| Diagnosis | Process variable variability (`pv_variability`) | survey | done | same |
| Diagnosis | Manual mode fraction (`manual_mode_fraction`) | survey | done | same |
| Diagnosis | Controller output saturation (`op_saturation_fraction`) | survey | done | same, `tests/test_rounds.py` (PIC-103) |
| Diagnosis | Setpoint activity (`setpoint_activity`) | survey | done | same |
| Diagnosis | Oscillation detection (`oscillation_autocorrelation`) | Thornhill and Hägglund 1997; regularity: Thornhill, Huang and Zhang 2003 | done | same, `tests/test_rounds.py` (LIC-102) |
| Diagnosis | Sensor noise ratio (`sensor_noise_ratio`) | survey | done | same |
| Diagnosis | Valve travel and reversals (`op_travel_reversal`) | survey | done | same |
| Diagnosis | Valve stiction screening (`stiction_screening`) | stick-slip model: Choudhury, Thornhill and Shah 2005; saturation ruled out first: Jelali and Huang 2010 | done (screening of the OP pattern; no PV-OP shape test, G28) | same, `tests/test_rounds.py` (FIC-105) |
| Diagnosis | Valve stiction quantification | Choudhury 2006, Jelali and Huang 2010 | partial: screening only, no Horch cross-correlation, ellipse or bicoherence test (G28); ISDB oracle not pinned (G3) | `tests/oracles` |
| Diagnosis | Loop interaction (`interaction_cross_correlation`) | survey | done | same |
| Diagnosis | Minimum-variance benchmark (Harris index, `harris_index`) | Harris 1989, Horch and Isaksson 1999 | done | `tests/test_harris.py` |
| Algorithms | Configurable assessment as diagrams of typed blocks, checked before they run; outputs on the asset, as events and in the historian | survey | done (44 blocks, 5 shipped algorithms, 0.2 protocols converted; `docs/blocks-and-algorithms.md`) | `tests/test_algorithms.py` |
| Engine | Scheduled assessment of the whole plant | survey | done (round, interval/hourly/daily/weekly/once schedules) | `tests/test_schedules.py`, `tests/test_engine_reliability.py` |
| Engine | Thousands of loops per round | survey | done: 2000 loops in ~2.5 min (bench, 4 processes) | `python -m linkcraft.bench` |
| Reporting | Prioritised plant overview | survey | done (loops list, status and health) | `tests/test_api.py` |
| Reporting | Per-loop diagnosis report | survey | partial: PDF with score, limiting criterion, trends and findings; no economic impact or recommendation (G1) | `tests/test_api.py` |
| Reporting | Periodic portfolio report | survey | done (weekly PDF) | `tests/test_api.py` |
| Workflow | Engineering actions on findings | survey | missing (parked, G18) | |
| Tuning | PID tuning suggestions from closed-loop data | survey | missing | |
| Security | Sign-in, roles, audit of changes | survey | done (PlantCraft tokens, viewer/editor/admin, v1 audit) | `tests/test_api.py` |

## Oracles

| Oracle | Cases | Expected verdict from | Passed (2026-10-19) |
|---|---|---|---|
| Simulator loops with known faults (`tests/oracles/test_simulator_oracle.py`) | 10: healthy (2), oscillation from an external disturbance, oscillation from tuning, stuck valve, saturation, sensor noise, frozen sensor, manual mode, setpoint changes | how each loop was built with PlantCraft Simulator's dynamics (`tests/oracles/simulator.py`, copied from PlantCraft Simulator) | 10 of 10 |
| International Stiction Database (`tests/oracles/test_isdb_oracle.py`) | loops of Jelali and Huang (2010) | the labels the book publishes, transcribed into `tests/oracles/isdb_labels.toml` with their table cited; none yet | skipped: archive not pinned, labels not transcribed (G3) |
