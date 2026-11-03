# Testing

```sh
make ci          # everything CI runs; green before every commit
make test-fast   # the Python tests without the slow tier, while you work
make e2e         # browser journeys (Playwright and Chromium)
```

`make ci` is `deps standard lint frontend test`:

| Step | What it runs |
|---|---|
| `deps` | Installs the SDK from `vendor/` and the app with its `dev` extras |
| `standard` | `plantcraft-app check .` (the manifest, the layout, the vendored hashes, the Makefile targets) and `i18n_check --strict` |
| `lint` | `ruff check` and `ruff format --check` (`make format` fixes them) |
| `frontend` | `npm ci`, `npm run build`, `npm test` (Vitest) |
| `test` | `pytest` |

The same runs on GitHub for every push and pull request (`.github/workflows/ci.yml`).

## The fake PlantCraft

The Python tests never need a real PlantCraft. `tests/plant.py` starts `FakePlantCraft` from
the SDK with the suite's test plant: the Simulator's loops as assets, twelve hours of their
signals, and four people.

| Person | In this app |
|---|---|
| `admin` | Admin |
| `engineer` | Editor |
| `operator` | Viewer |
| `outsider` | No access |

`tests/conftest.py` gives the fixtures:

```python
def test_viewers_read_only(runtime, fake, client):  # client is `engineer`
    note_id = client.post("/api/notes", json=note()).json()["note_id"]
    with client_for(runtime, fake, "operator") as operator:  # another person
        assert operator.post("/api/notes", json=note()).status_code == 403
        assert operator.get(f"/api/notes/{note_id}").status_code == 200
```

`fake.audit_log` holds the audit lines the app wrote; `fake.links` what it sent to PlantCraft
(events, calendar items, to-dos, model calls). The fake **holds the app to its `app.toml`**: a
read or write the manifest does not declare is refused with 403, and at the end of the session
`apptest.permission_problems` fails the run if the app used a permission it does not declare.

## The suite's rules, as tests

`tests/test_suite_rules.py` runs the checks of `plantcraft_sdk.apptest` that every app of the
suite runs:

| Test | Fails when |
|---|---|
| `test_offline_by_default` | Code or interface fetches an `http(s)://` address at run time |
| `test_layers_only_point_down...` | A package imports from a higher layer (`LAYERS`) |
| `test_only_suite_talks_to_plantcraft_for_the_app` | The service client is used outside `suite/` |
| `test_routers_go_through_the_services` | A router touches a store directly |
| `test_what_app_toml_contributes_is_wired` | `app.toml` `[contributes]` names a route that does not exist |
| `test_the_screens_use_the_shared_ui_instead_of_copies` | A screen copies a block of `@plantcraft/ui` |
| `test_the_image_follows_the_manifest` | The Dockerfile disagrees with `app.toml` (user, port, labels) |
| `test_every_api_route_answers_junk_without_a_server_error` | Any route answers 5xx to junk input |
| `test_no_api_route_answers_without_a_token` | A route forgot its access check |
| `test_api_floor` | Fewer API operations than `tests/floors.toml` says |

`tests/test_app_standard.py` checks that `app.toml`, `pyproject.toml`, `__init__.py` and the
Makefile agree, and that the standard endpoints answer as they must.

## Writing a test

Write it first, see it fail, then make it pass. For every rule of an object, test:

- the rule itself (what is saved, what is answered);
- bad input: 422 with a message;
- a missing object: 404;
- a viewer cannot change it: 403; a person without access sees nothing: 403; no token: 401;
- every crash you fix: a small test with the input that crashed, so it never comes back.

The numbers in `tests/floors.toml` only rise: when the junk test reaches more routes, raise the
floor in the same change.

## Browser journeys

`tests/e2e/` runs the real server with the built interface against the fake PlantCraft, in
Chromium, with Playwright:

```sh
pip install -e ".[e2e]" && python -m playwright install chromium   # once
make e2e
STARTER_E2E_SCREENSHOTS=shots make e2e   # also saves a screenshot of each step in shots/
```

Without Playwright installed, the journeys are skipped (so `make ci` stays quick); `make e2e`
requires it. Add a journey when a person completes a task on a page: sign in, do the task, see
the result.
