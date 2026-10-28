<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="StarterCraft"></p>

# StarterCraft: the app template of PlantCraft

The smallest complete app of the [PlantCraft](https://github.com/PlantCraft/PlantCraft)
suite, made to be copied. It keeps a note on any asset of the plant: listed, searched (Ctrl+K),
audited and kept in the app's own database. Around that one object it has every part a suite app
has: the manifest, the server on the SDK, the interface on the suite's frame, help pages, tests
that hold it to the suite's rules, the image and the signed package.

The suite, and this template, were built with Claude Code. The template is made for the same way
of working: the prompts in [`prompts/`](prompts/README.md) take an agent from a copy of this
folder to a new app that runs inside PlantCraft.

## Make an app from it

```sh
make rename NAME=Logbook      # once: LogbookCraft, id logbook, prefix /logbook/
make ci                       # app standard, lint, interface build and tests, pytest
make dev                      # the Simulator, PlantCraft on :8060 and the app on :9100
```

Then open http://127.0.0.1:8060 (the demo has no password; the profile menu switches people)
and open the app from the launcher. `make dev` needs a PlantCraft checkout (the repository's root when
this folder is `templates/app`, else `../PlantCraft`, or `PLANTCRAFT_DIR=`) with PlantCraft
installed in the same Python:

```sh
cd ../PlantCraft   # or the repository's root
python3 -m pip install -e sdk/python -e ".[server,opcua]" && python3 -m pip install -e simulator
```

To install it as a package on a PlantCraft stack: `make dev-package` (signed with PlantCraft's
development key, `make dev-publisher` there) and Apps > Install from file.
[`prompts/05-package-and-install.md`](prompts/05-package-and-install.md) has the steps for a
production key.

## What each part does

| Path | What it is |
|---|---|
| [`app.toml`](app.toml) | The manifest: id, name, version, prefix, port, uid, permissions. The launcher, the Apps page, the package, the image labels and `/api/meta` read it. |
| `src/starter/notes/` | The app's object: `NoteDraft` (what a person may send, checked) and `NoteStore` (its SQLite table). |
| `src/starter/api/` | `runtime.py` (settings, database, PlantCraft clients), `deps.py` (who may do what), `routers/` (the routes), `app.py` (the suite's API frame). |
| `src/starter/meta.py`, `docs/help/` | The manifest and the help pages served at `/api/meta` and `/api/help`. |
| `frontend/src/` | `App.tsx` (routes), `pages.tsx` (sidebar), `NotesPage.tsx` (the page), `api.ts` (calls). All on `@plantcraft/ui`. |
| `tests/` | `conftest.py` and `plant.py` (a fake PlantCraft with a small plant), `test_notes.py` (the object), `test_app_standard.py` and `test_suite_rules.py` (the suite's rules), `e2e/` (browser journeys). |
| `vendor/` | The SDK wheel and the interface package, with their SHA-256: the image is built offline. |
| `Dockerfile`, `deploy/` | The image: three stages, hashed dependencies, non-root, read-only root. |

## The rules

[`AGENTS.md`](AGENTS.md) lists the rules every suite app follows (read-only on the plant, refer
to assets and signals by id, sign-in and audit through PlantCraft, offline, one frame, tests as
the gate) and points to the full standard in PlantCraft (`docs/app-standard.md`).

## License

Apache-2.0 ([LICENSE](LICENSE)). Third-party assets and libraries: [ATTRIBUTION.md](ATTRIBUTION.md).
