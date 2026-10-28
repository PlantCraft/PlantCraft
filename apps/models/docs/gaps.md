# Gaps

> **Updated:** 2026-10-23

Every known shortfall of PlantCraft Models, ranked by user impact. `B` marks a blocker for the next stage.
When a gap closes, delete its row in the same change and log it in `ROADMAP.md`.

| Id | Gap | Impact | B |
|---|---|---|---|
| G4 | Only the Modelica Standard Library: process plants need fluid and thermal libraries (Buildings, ThermoSysPro, ExternalMedia...) and uploading a library | high | |
| G5 | Optimization studies are there (2026-10-26: decision values with bounds, objective and constraints on indicators, SciPy's Nelder-Mead, COBYLA, SLSQP); still missing: fitting parameters to plant data (an objective on the error to a plant signal) | medium | |
| G11 | Studies run in Models' own queue: the suite's queue panel and metrics (plantcraft-sdk 0.17.0, @plantcraft/ui 0.22.0, from Link) not adopted yet | low | |
| G12 | Projects are not listed in the left menu (needs `children` in the suite frame's menu) | low | |
| G1 | No one-click FMU hand-off to Twin: the FMU is downloaded and uploaded in Twin by an administrator | medium | |
| G2 | The parameter dialog is a flat list: no `Dialog(tab, group)`, enumerations or `replaceable` choices, so library components with many parameters are hard to set | medium | |
| G6 | No linearisation or step responses for control design (would link to Link's loop tuning) | medium | |
| G9 | The runner has no seccomp profile or user namespace (defense in depth beyond capabilities and limits) | medium | |
| G3 | No connection routing (orthogonal lines that avoid components, editable points): large diagrams get crossed lines | low | |
| G7 | No member completion or go to definition in the editor | low | |
| G8 | No Git for projects | low | |
| G10 | Portuguese catalog for `t()` (parked by the owner: English first) | low | |
