# Gaps

> **Updated:** 2026-10-31

Every known shortfall of PlantCraft Alarms, ranked by user impact. `B` marks a blocker for the next stage.
When a gap closes, delete its row in the same change and note it in `CHANGELOG.md`.

| Id | Gap | Impact | B |
|---|---|---|---|
| G3 | No rate-of-change or deviation-from-setpoint alarms, common alarm types in plants | high | |
| G6 | No export of the master alarm database (the DCS list is imported, Rules › Import alarm list) | medium | |
| G4 | Only one permissive per alarm (no multi-state mode tables, ISA-18.2 advanced methods); a flood is one message a person, not a suppression of the alarms | medium | |
| G7 | No printable rationalization and performance report (PDF) for audits and management review | low | |
| G8 | Portuguese catalog for `t()` (parked by a maintainer: English first) | low | |
