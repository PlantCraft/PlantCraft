# Gaps

> **Updated:** 2026-10-25

Every known shortfall of PlantCraft View, ranked by user impact. `B` marks a blocker for the next stage.
When a gap closes, delete its row in the same change and note it in `CHANGELOG.md`.

| Id | Gap | Impact | B |
|---|---|---|---|
| G14 | Packages are built and verified only with a development key; the real PlantCraft publisher key is a maintainer's, so no `.pcapp` signed by it exists yet | medium | |
| G1 | No event frames, annotations or alarm marks on trends | medium | |
| G3 | The editor finds assets and signals by kind and text; there is no asset tree browser | medium | |
| G8 | PlantCraft has no "dashboards only" grant for PlantCraft View yet: a person reaches PlantCraft View by its `apps` claim (viewer or editor); the monolith's "only dashboards" role maps to viewer here | medium | |
| G4 | Layout by width, height and order per card; no drag-and-drop | medium | |
| G5 | No export of a dashboard to image or PDF (a card's data downloads as CSV; reports make PDFs) | medium | |
| G15 | Reports: one report per asset (a variable) and reports built from a notebook are not offered yet; notebooks never run on the server | medium | |
| G6 | No `tests/test_isolation.py` here (the suite's isolation test lives in PlantCraft); no pip-audit, npm audit or CycloneDX SBOM in this repository's CI | medium | |
| G9 | A failed audit write (PlantCraft down) is logged and dropped, not queued and retried | medium | |
| G10 | Trend windows over 366 days, and statistics other than API v1's aggregations, are not offered | low | |
| G11 | Interface in English only; the `t()` hook is in place, no Portuguese catalog | low | |
| G7 | SPEC.md research table lists the vendor tools studied but not yet the links to their public pages | low | |
