# Changelog

All notable changes to this app are recorded here ([Keep a Changelog](https://keepachangelog.com)).

## [Unreleased]

## [0.1.0] - 2026-11-01

### Added

- **PlantCraft PID, the suite's first closed app.** The P&ID reader and the plant map move out of
  PlantCraft Documents into an app of their own: send P&IDs (PDF, SVG, DEXPI or a scan) in
  **Drawings**, check what was read in **Diagrams**, and work on the joined **Plant map** (Correct /
  Wrong, lists, DEXPI, asset file, a Markdown summary). Drawings keep revisions by number.
- **Closed and licensed.** The image carries the app compiled with Nuitka (no source, no bytecode;
  the build fails if any is left) and the app works only with a `.pclicense` its publisher signed
  for this installation (`[license] required = true`, 14 days of grace, then 402). The licence's
  `sheets` limit caps how many drawings it holds.
