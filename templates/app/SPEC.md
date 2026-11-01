# SPEC: StarterCraft

What the app does and the public sources it relies on (AGENTS.md, "Clean room"). An app made from
the template replaces this file with its own.

## Purpose

A note on any asset of PlantCraft's asset tree: the smallest object that shows every part of a
suite app (manifest, store, API, interface, help, tests, image, package).

## Object

| Field | Rule |
|---|---|
| `note_id` | Given by the store, never by a person |
| `asset_id` | A PlantCraft asset id; the name is read from PlantCraft when shown |
| `text` | 1 to 4,000 characters |
| `created_by`, `created_at`, `updated_at` | Set by the server |

## API

`GET /api/notes`, `POST /api/notes`, `GET|PUT|DELETE /api/notes/{note_id}`, plus the standard
`/healthz`, `/api/me`, `/api/meta`, `/api/help`.

## Sources

None outside the PlantCraft suite (its app standard and SDK).
