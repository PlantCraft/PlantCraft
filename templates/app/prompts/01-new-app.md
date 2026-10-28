# 01: A new app from the template

```text
Read AGENTS.md and README.md of this folder, and docs/app-standard.md of PlantCraft (the
repository's root, or ../PlantCraft).

I want an app called <Name>Craft (id <name>) for <who uses it and for what, in two sentences>.
Its main object is <object>: <what one record holds, field by field, with the limits of each>.
It refers to <assets | signals | both> of PlantCraft by id.

1. Run `make rename NAME=<Name>` (pick PORT and UID free in the suite table if 9100/20100 are
   taken on my stack) and `make ci`; it must be green before you change anything else.
2. Turn the notes into <object>: the contract and store in src/<name>/<object>s/, the routes in
   api/routers/, audit on every change, the page in frontend/src/, the help page in docs/help/.
   Keep the layers of AGENTS.md and update LAYERS in tests/test_suite_rules.py.
3. Tests first for each rule of the object (limits, bad input answers 422, a missing record 404,
   a viewer cannot write). Update tests/floors.toml when the number of API operations grows.
4. Fill app.toml (summary, description, category, permissions it really needs), SPEC.md,
   ROADMAP.md, CHANGELOG.md and docs/devlog.md.
5. `make ci` and `make e2e` green; then show me the page: run `make dev` and take a screenshot of
   it with Playwright.
```
