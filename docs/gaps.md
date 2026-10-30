# Gaps

> **Updated:** 2026-10-23

Every known shortfall of PlantCraft (the central app), ranked by user impact. Each app's gaps are in its own `apps/<app>/docs/gaps.md`.
`B` marks a blocker for the next stage. When a gap closes, delete its row in the same commit and
log it in `ROADMAP.md`.

| Id | Product | Gap | Impact | B | Estimate |
|---|---|---|---|---|---|
| G11 | Release | Docker offline bundle and guide done (`make bundle`, `docs/install-offline.md`, 2026-10-19); signed releases for x86_64 and arm64 (0.3.0); still missing: wheelhouse with the built UI for installs without Docker, Windows installer without admin | high | B | |
| G12 | Core | Docker deployment has one data folder, backup before upgrade and `install.sh --rollback` (2026-10-19); installs without Docker still lack them and `plantcraft rollback` | high | B | |
| G13 | Release | Docker image pinned (base digests, hashed `deploy/requirements.lock`), CycloneDX SBOM of Python and npm dependencies, pip-audit, npm audit and SHA-256 sums in CI (2026-10-19). TODO: SBOM of the images' OS packages and the Caddy binary (syft or `docker buildx --sbom`); `pyproject.toml` ranges stay unpinned for library users | medium | | |
| G2 | Core | PI Web API source never run against a real server; no validation on real plant data | high | B | |
| G6 | Frontend | Plotly axes use day-first dates in every language | low | | |
| G7 | Core | Text stored at runtime (seed data, asset names and descriptions from a scenario) stays in the language it was written in | low | | |
| G8 | Release | No release pipeline (wheel, Docker image, Windows installer) | low | | |
| G15 | Core | A scenario must name a data source: the Docker site scenario points at an empty CSV (`deploy/site/no-data.csv`) until sources are optional | low | | |
| G16 | Core | Apps page done (2026-10-19, [app-package.md](app-package.md)): signed `.pcapp` from a file or `install.sh --add`, online catalog (off until an admin turns it on), external apps with an app key; checked against the app standard (id, suite table, `plant_write`, `outbound`); a no-network installer is the only part with Docker. TODO: (1) **licence**: PlantCraft has no licence notion today, so every package from a trusted publisher installs; the licence check of app-standard.md section 8 waits for it. (2) `[permissions]` are shown and audited but app keys have no scopes yet, so they are not enforced. (3) The proxy is recreated on every app change (a few seconds without HTTPS) | medium | | |
