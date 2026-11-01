# Documentation

Everything you need to turn this template into an app of your own and ship it to a PlantCraft
installation. Read them in this order the first time; afterwards, jump to the one you need.

| Guide | What it answers |
|---|---|
| [quickstart.md](quickstart.md) | From "Use this template" to your app running inside PlantCraft, in about 15 minutes |
| [concepts.md](concepts.md) | What an app is in PlantCraft, what it owns and what it always asks the platform for |
| [structure.md](structure.md) | Every folder and file of the template, and the layers the code keeps |
| [backend.md](backend.md) | The server on `plantcraft-sdk`: settings, access, audit, reading the plant, errors |
| [data.md](data.md) | The app's own database: stores, schema changes (migrations), backup |
| [frontend.md](frontend.md) | The interface on `@plantcraft/ui`: frame, pages, tables, forms, help, tour |
| [translations.md](translations.md) | `t()`, the language catalogs and the check that holds them complete |
| [testing.md](testing.md) | `make ci`, the fake PlantCraft, the suite's rules as tests, browser journeys |
| [packaging.md](packaging.md) | `app.toml` key by key, the image and the signed `.pcapp` package |
| [publishing.md](publishing.md) | Versions, changelog, releases, keeping the SDK up to date, open and closed apps |
| [recipes/](recipes/README.md) | Code to add one more thing: search, widgets, events, Desk, a language model, signals, results, background work |

The rules every app follows are in [`../AGENTS.md`](../AGENTS.md); the full app standard is
`docs/app-standard.md` in the [PlantCraft repository](https://github.com/PlantCraft/PlantCraft).
When this documentation and the standard differ, the standard wins.

The other files here belong to the app itself and you keep them up to date as you work:
`STATUS.md` (where the app stands), `devlog.md` (one line per working session), `gaps.md`
(known gaps), `help/` (the help pages people read inside the app) and `images/` (the logo).
