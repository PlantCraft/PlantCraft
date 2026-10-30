# Gaps

> **Updated:** 2026-10-25

Every known shortfall of PlantCraft Alarms, ranked by user impact. `B` marks a blocker for the next stage.
When a gap closes, delete its row in the same change and note it in `CHANGELOG.md`.

| Id | Gap | Impact | B |
|---|---|---|---|
| G3 | No rate-of-change or deviation-from-setpoint alarms, common alarm types in plants | high | |
| G6 | No import or export of the master alarm database (CSV/Excel); plants start from their DCS alarm list | high | |
| G4 | No state-based alarming (suppress by a plant state signal; ISA-18.2 advanced methods); flood is one message a person, not a suppression of the alarms | medium | |
| G5 | No operator positions (consoles): the ISA-18.2 targets are per operator, the figures are per plant | medium | |
| G7 | No printable rationalization and performance report (PDF) for audits and management review | low | |
| G8 | Portuguese catalog for `t()` (parked by a maintainer: English first) | low | |
