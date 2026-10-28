# Prompts for building an app

Each file is a prompt to paste into Claude Code (or another coding agent) opened in this folder.
They are written for this template and follow its `AGENTS.md`; replace the words in angle
brackets. Run them in order for a new app; `02` and `03` again for each new object or page.

| Prompt | What it does |
|---|---|
| [`01-new-app.md`](01-new-app.md) | Names the app and turns the notes into your app's first object, green at the end |
| [`02-add-object.md`](02-add-object.md) | Adds an object: contract, store, routes, audit, tests |
| [`03-add-page.md`](03-add-page.md) | Adds a page on the suite's frame, with its test and a screenshot |
| [`04-try-in-platform.md`](04-try-in-platform.md) | Runs the app inside a local PlantCraft and checks it as a person would |
| [`05-package-and-install.md`](05-package-and-install.md) | Builds the image and the signed package, and installs it on a PlantCraft stack |

Before you start, have a PlantCraft checkout beside this folder (`../PlantCraft`) or work in
`templates/app` of the PlantCraft repository, so the agent can read the suite's standard
(`docs/app-standard.md`) and run the app inside the platform.
