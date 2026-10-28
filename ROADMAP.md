# PlantCraft roadmap

> **Last reviewed:** 2026-10-25 · **Stage:** alpha

Readiness of each app against what tools of its category offer. "Measured" numbers
come from tests and oracles; "estimated" ones are judgement. Detail per product in
each app's own `ROADMAP.md`; the ranked work list is `docs/gaps.md`.

| App | Category | Stage | Version | Detail |
|---|---|---|---|---|
| PlantCraft | Central app: people, groups, access, sources, signals, assets, Desk, API v1 | alpha | 0.4.0 | this file, `docs/gaps.md` |
| Link | Control loop performance, signal quality, process models, blocks and algorithms | alpha | 0.4.0 | `apps/link/ROADMAP.md` |
| Historian | Process historian: PI Web API, OPC UA and CSV sources, archive | alpha | 0.4.0 | `apps/historian/ROADMAP.md` |
| View | Dashboards, trends and scheduled reports | alpha | 0.4.0 | `apps/view/ROADMAP.md` |
| Alarms | Alarm management (ISA-18.2): rules, notifications, history | alpha | 0.4.0 | `apps/alarms/ROADMAP.md` |
| Models | Modelica workbench with an OpenModelica runner, studies | alpha | 0.4.0 | `apps/models/ROADMAP.md` |
| Simulator | OPC UA plant simulator; runs the demo | beta | 0.5.0 | `simulator/ROADMAP.md` |

Readiness per area (measured or estimated) is in each app's own `ROADMAP.md`. CPMCraft and
DataCraft (2026-10-20) and Twin (2026-10-22) merged into Link; TrendCraft is View.

## Progress log

| Date | Change |
|---|---|
| 2026-10-19 | Repository opened as PlantCraft: English source with pt-BR translation, new visual identity, rules, hostile-input tests and floors. |
| 2026-10-19 | Direction: separate apps; PlantCraft is the central app and CPMCraft moves to its own repository (MVP plan). |
| 2026-10-19 | PlantCraft becomes the central app only; the analysis lives in CPMCraft. Closed G5 (product names: the launcher names each app) and G14 (no language model in PlantCraft; specialists parked in CPMCraft, its G18). G1 and G3 moved to CPMCraft. Spec in `SPEC.md`. |
| 2026-10-19 | Closed G31: the demo (`run_opcua_demo.py`, compose profile `demo`) runs the Simulator 0.4.0 (`plantcraft loops serve`, image `plantcraft`, namespace `urn:processcraft:plantcraft`); `processcraft/simulator` removed. |
| 2026-10-20 | Closed G32 (decision D2): API v1 signal ids are `<source id>:<tag>`, references `signal:<source id>:<tag>` (never percent-encoded); bare tags of one source read until v1 is frozen; stored refs renamed once; `plantcraft-sdk` 0.5.0. |
| 2026-10-20 | Closed G4 (the synthetic signal oracle lives in LinkCraft, `tests/oracles/test_signal_synthetic_oracle.py`, DataCraft merged there) and G9 (PlantCraft Twin is built: `twincraft` repository, compose service `twincraft`). |
| 2026-10-20 | Closed G35: `make e2e-bundle` (`ci/e2e-bundle.sh`) builds every image from the app checkouts, makes the bundle, installs it in an empty folder with `--all-apps --public-demo` and walks the 13 suite journeys; first run from every main: 9 containers healthy in 142 s, 13 of 13 journeys. Runs on a developer machine or the Mac mini, never in GitHub CI. |
| 2026-10-20 | Closed G10: PI Web API sessions refuse every write verb (`ReadOnlySession`) and `tests/test_read_only_plant.py` fails if plant-facing code calls an OPC UA write or an HTTP write verb; with sign-in required on a network address and the route permission walk, the read-only rule is tested. |
