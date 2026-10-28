# PlantCraft View spec

Category: plant dashboards and trend viewers: screens of KPIs, trends, bars and tables over
historian data, for engineers' desks and control room walls, shared with people who do not
use the engineering tools. Tools studied (research only): AVEVA PI Vision, Seeq Organizer,
Grafana (with historian data sources), Canary Axiom, Ignition Perspective dashboards. Sources
are public only (clean room, see AGENTS.md).

## Sources

| Source | Link | Read on |
|---|---|---|
| Vendor product pages and public documentation of the tools above | links to be added (G7) | |
| PlantCraft API v1 (`docs/api-v1.md` in PlantCraft): assets, signals, series, values, audit | PlantCraft repository | 2026-10-19 |
| The BI dashboard of the PlantCraft monolith (cpm PR #8, public links from PR #11), the code this app replaces | PlantCraft authors | 2026-10-19 |

## Where data comes from

Decided 2026-10-19:

1. **Plant data and the asset tree only from PlantCraft API v1**, through
   `plantcraft_sdk.client`. PlantCraft View stores no samples and no assets; it stores dashboards
   (`dashboards`, one JSON list of cards each) and public links (`dashboard_shares`, token
   SHA-256 only) in its own SQLite.
2. **A card item names a signal three ways**: `signal_id`; `asset_id` + `role` (the asset's
   signal of that role, resolved on every read, so a renamed tag follows the asset); or
   `$context` + `role` (the role of the asset picked on the dashboard, whose kind is the
   dashboard's `context_kind`).
3. **Saved dashboards read as PlantCraft View** (service token from the app key) and are shared by
   every viewer and public link through a TTL cache; editors' pickers and previews read as the
   editor. Why: a dashboard is a published report, and a control room screen with 20 viewers
   must cost PlantCraft one read, not 20.

## Features

| Area | Feature in the target tools | Source | Ours | Test or oracle |
|---|---|---|---|---|
| Data | Read historian data through one platform API | all | done, PlantCraft API v1 only | `tests/test_suite_rules.py`, `tests/test_api.py` |
| Data | Batch reads of many trend lines | all | done (`POST /api/v1/series`, one request per card) | `tests/test_query.py` |
| Data | Aggregates over a window (last, mean, min, max, ...) | all | done (API v1 `value?agg&window`) | `tests/oracles/test_pandas_oracle.py` |
| Data | Shared cache so many viewers cost one read | Grafana, PI Vision | done (TTL cache, `DASHCRAFT_CACHE_SECONDS`) | `tests/test_query.py` |
| Assets | Asset-relative displays (one display, many assets) | PI Vision, Seeq | done (`$context` + role, picker by kind) | `tests/test_api.py` |
| Assets | Asset tree browser in the editor | all | partial: asset and signal search by kind and text, no tree (G3) | `tests/test_api.py` |
| Cards | Value tile with limits | all | done (KPI with warning and alarm limits) | `tests/test_model.py` |
| Cards | Trend of several signals, two scales | all | done (up to 12 lines, two units on two axes) | `tests/test_query.py`, e2e |
| Cards | Bar and table of values | all | done | `tests/test_query.py` |
| Cards | Trend that still shows something when the window is empty | PI Vision | done (anchors to the newest sample, says so) | `tests/test_query.py` |
| Cards | Event frames, annotations, alarms on trends | PI Vision, Seeq | missing (G1) | |
| Cards | Results of other apps (PlantCraft Analytics loop health and signal quality) | Seeq | done (`result` items: producer's status, score, stale when expired; on trends, the history the app archives in PlantCraft Historian) | `tests/test_query.py`, e2e |
| Cards | Process graphics (P&ID-style displays) | PI Vision, Ignition | missing, out of scope for now | |
| Screens | Auto refresh, full screen | all | done (0, 15, 30, 60, 300 s; full screen) | e2e |
| Screens | Time range picker, URL that keeps the view | all | done (`?asset&w&screen`) | e2e |
| Screens | Drag-and-drop layout | Grafana, PI Vision | partial: width, height and order per card, no drag (G4) | |
| Sharing | Read-only link without sign-in | Grafana | done (hashed, revocable, can be turned off) | `tests/test_public.py` |
| Sharing | Dashboard templates from the asset model | Seeq | done (loop detail, unit overview, in New dashboard; nothing saved before Save) | `tests/test_folders.py`, e2e |
| Sharing | Folders with who sees and who edits (people, groups) | Grafana | done (one level; server-side filter everywhere) | `tests/test_folders.py`, e2e |
| Sharing | Version history, restore; export and import as JSON | Grafana | done (last 30 saves) | `tests/test_folders.py`, e2e |
| Screens | Shared cursor across charts, kiosk mode, default time window, tags | Grafana | done (Config › Display, Time, General) | e2e |
| Sharing | Export (image, PDF, CSV) | all | partial: a card's data as CSV; reports as PDF; no image of a dashboard (G5) | `tests/test_reports.py` |
| Reports | Scheduled reports sent as PDF (daily, weekly, monthly) to people and groups | Grafana, PI Vision, Seeq | done (sections: text, cards, events, page breaks; Messages notification with the PDF; every PDF kept; Desk's calendar) | `tests/test_reports.py`, e2e |
| Reports | Event lists and counts over the period (alarms, findings) | PI Vision, Seeq | done (any event kind the installed apps declare) | `tests/test_reports.py` |
| Security | Sign-in, roles, audit of changes | all | done (PlantCraft tokens, viewer/editor, v1 audit) | `tests/test_api.py` |
| Security | Concurrent edits without lost changes | Grafana | done (409 with the current version) | `tests/test_api.py` |

## Oracles

| Oracle | Cases | Expected values from | Passed (2026-10-19) |
|---|---|---|---|
| pandas over a recorded file (`tests/oracles/test_pandas_oracle.py`): gaps, irregular samples, a spike; KPI last, mean, min, max and std over 15m, 1h, 8h and 24h (20), and trend points as step means (1) | 21 | pandas on the same samples | 21 of 21 |
