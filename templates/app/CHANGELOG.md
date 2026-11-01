# Changelog

All notable changes to this app are recorded here ([Keep a Changelog](https://keepachangelog.com)).

## [Unreleased]

## [0.2.0] - 2026-11-01

- Only the basics: the template keeps the notes (list, create, change, delete, audit),
  one page, a help page in English and Brazilian Portuguese, the tests, the image and the
  package. Search, widgets, the `note.written` event, Desk's follow-ups, the summary from a
  model and `#starter_note` references left the code and became recipes in `docs/recipes/`.
- Full documentation in `docs/`: quickstart, concepts, structure, server, data, interface,
  translations, testing, packaging (every `app.toml` key, and the keys PlantCraft PR #179 will
  add) and publishing.

- Earlier in this version, then moved to the recipes above: processcraft-sdk 0.35: the standard inside of an app. `suite/` is the only code that talks to
  PlantCraft (events, Desk, a model); `notes/` has `models.py`, `store.py` and `service.py`;
  routers stay thin. A note may ask for a follow-up (a day and a person): it shows on Desk's
  calendar and in that person's to-do. **Summarise** asks the model Setup gives the use
  `summary` (off until chosen). `#starter_note:<id>` references open the note.
- processcraft-sdk 0.28 (an app without an app key reports its conditions); nothing else changes.
- An example event, `note.written`, declared in `app.toml` and written by name
  (processcraft-sdk 0.26).

## [0.1.0] - 2026-10-23

- First version: notes on assets (list, filter, create, change, delete), audited; Ctrl+K search;
  help page; the suite's app standard and rules as tests; the image and the signed package.
