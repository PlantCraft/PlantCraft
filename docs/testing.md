# Testing: one layout for every app of the suite

Every app of the suite tests itself the same way, with the same files, helpers and limits, so a
person (or an agent) who knows one app's tests knows them all, and the suite can grow without its
tests growing slow. The rules below hold in every app.

## The files

| File | What it holds | Written once in |
|---|---|---|
| `tests/conftest.py` | the app's fixtures: `fake` (a `FakePlantCraft`), `runtime`, `client` | the app (its runtime is its own) |
| `tests/plant.py` | the test plant the fake serves: `plant_fake(app_id, name, url)` | `plantcraft_sdk.testplant` (the Simulator's loops, users, assets) |
| `tests/test_suite_rules.py` | the suite's rules, one line each: offline, layers, image, hostile inputs, API floor | `plantcraft_sdk.apptest` |
| `tests/test_app_standard.py` | `app.toml` against the code, `/api/meta`, `/api/help`, `assets/<id>` | the app, on `plantcraft_sdk.apptest` |
| `tests/test_<area>.py` | the app's own behaviour, one file per area (`test_api.py`, `test_engine.py`...) | the app |
| `tests/oracles/` | public data with known answers (AGENTS.md, section 5) | the app |
| `tests/e2e/` | browser journeys (Playwright); `conftest.py` builds the runtime only | `plantcraft_sdk.e2e` (servers, Chromium, pages) |
| `tests/floors.toml` | measured numbers that only rise | the app |

A rule that every app checks the same way goes into `plantcraft_sdk.apptest`, never into a copy:

- `offline_problems(root, app_id, network_modules=..., client_builders=...)`: nothing external at
  runtime; only the named modules open network connections or build a `PlantCraftClient`.
- `layer_problems(root, app_id, layers, allowed=...)`: imports only point down; no app imports
  another app or a plant protocol.
- `image_problems(root)`: the Dockerfile follows `app.toml` (user, port, health, labels, SBOM).
- `suite_problems(root, app_id)`, `router_problems(root, app_id)`,
  `contribution_problems(root, app_id, routes)` and `ui_copy_problems(root, ui_src)`: the inside
  of an app keeps the standard layout (`docs/app-standard.md`, section 5): PlantCraft is reached
  only from `suite/`, routers stay thin, every `[contributes]` table has its code, and nothing of
  `@plantcraft/ui` is copied.
- `api_routes(app)` and `hostile_failures(client, real=..., bodies=..., keep=...)`: every route,
  fed junk, answers 4xx, never 500.

## Two tiers and a time budget

- **Fast** (default): unit, contract (against `FakePlantCraft`), the suite rules. Each test
  stays under its budget. This is the loop while working: `make test-fast`.
- **Slow** (`@pytest.mark.slow`): what must take long on purpose, such as hostile inputs over
  every route, oracles, benches, real sockets (OPC UA), worker processes. Marked, never by accident.
- `make test` and `make ci` run both tiers; CI on a pull request runs `make ci`.

The budget lives in each `pyproject.toml` and is enforced by the SDK's pytest plugin
(`plantcraft_sdk.pytest_budget`, loaded automatically where the table exists):

```toml
[tool.plantcraft.tests]
test_seconds = 10     # an unmarked test (setup + call + teardown)
slow_seconds = 120    # a test marked slow (tests/e2e and tests/oracles are)
suite_seconds = 120   # the whole run
```

A test over its budget fails the run and is named; the fix is to make it faster or to mark it
slow on purpose. `suite_seconds` is set to about twice the measured run, and raised only with a
line in the devlog saying why. `PLANTCRAFT_TEST_BUDGET=off` turns the check off on a machine
busy with other work.

## Writing a new test

1. Put it in the file of its area; a new area gets a new `tests/test_<area>.py`.
2. Use the app's fixtures (`fake`, `runtime`, `client`) and `FakePlantCraft`; never a real
   PlantCraft, network or clock.
3. Name it as a sentence of what must hold (`test_a_refused_app_key_is_a_503_not_a_sign_in`).
4. A crash fix lands with the small test that failed before it (AGENTS.md, "Prove it").
5. Stay inside the fast budget, or mark it slow and say why in its docstring.
