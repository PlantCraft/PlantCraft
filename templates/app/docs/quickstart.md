# Quickstart

From an empty repository to your own app running inside PlantCraft. You need Python 3.11 or
newer, Node.js 22, `make` and Git. Docker is only needed to build the image at the end.

## 1. Make your copy

On GitHub, open this repository and press **Use this template** > **Create a new repository**.
Clone your new repository:

```sh
git clone https://github.com/<you>/<your-app>.git
cd <your-app>
python3 -m venv .venv && . .venv/bin/activate
```

(Working inside the PlantCraft repository instead? The template is `templates/app`; copy that
folder and continue from step 2.)

## 2. Give it a name, once

```sh
make rename NAME=Logbook              # LogbookCraft: id logbook, prefix /logbook/, LOGBOOK_* settings
make rename NAME=Logbook PORT=9110 UID=20110   # if another app of yours already uses 9100/20100
```

`NAME` is one word with a capital first letter. The command rewrites every file, moves
`src/starter` to `src/logbook` and `docs/help/starter.md` to `docs/help/logbook.md`. It refuses
to run twice. Pick a port from 9000 and a container user from 20000 that no other app on your
PlantCraft uses; `make ci` refuses any that one of the suite's own apps holds.

## 3. Check that everything is green

```sh
make ci
```

This installs the SDK from `vendor/`, checks `app.toml` against the app standard, checks the
translations, lints, builds and tests the interface and runs the Python tests. It must pass
before you change anything, and before every commit afterwards. The same command runs on GitHub
on every push (`.github/workflows/ci.yml`).

## 4. Run it on its own

```sh
make serve                            # http://127.0.0.1:9100/logbook/
```

On its own the app has no PlantCraft to sign people in, so the page sends you to a sign-in that
does not exist. That is expected: the next step gives it one.

## 5. Run it inside PlantCraft

Clone PlantCraft beside your app and install it in the same Python (once):

```sh
cd ..
git clone https://github.com/PlantCraft/PlantCraft.git
cd PlantCraft
python3 -m pip install -e sdk/python -e ".[server,opcua]" && python3 -m pip install -e simulator
cd ../<your-app>
```

Then:

```sh
make dev
```

It starts the Simulator (a small plant on OPC UA), PlantCraft on http://127.0.0.1:8060 and your
app on its port, registered in PlantCraft with an app key. Open http://127.0.0.1:8060, open your
app from the launcher and write a note. The demo has no password; the profile menu switches
between people with different roles, so you can see what a viewer may and may not do.

`make dev` looks for PlantCraft in `../PlantCraft` (or the repository root when the app is
`templates/app`). Set `PLANTCRAFT_DIR=/path/to/PlantCraft` for another place.

## 6. Make it yours

1. Write what the app is for in `SPEC.md` (purpose, the object, the API, public sources) and the
   first lines of `ROADMAP.md`.
2. Fill `app.toml`: `summary`, `description`, `category`, `publisher`, `homepage`
   ([packaging.md](packaging.md)).
3. Replace the notes with your own object: [structure.md](structure.md) says where each part goes,
   [backend.md](backend.md) and [data.md](data.md) how to write it, [frontend.md](frontend.md) its
   pages. Keep the tests green as you go ([testing.md](testing.md)).
4. Rewrite `docs/help/<id>.md` for the people who will use the app.
5. Need search, a widget, an event for Alarms or a to-do in Desk? Take the recipe from
   [recipes/](recipes/README.md).

Working with Claude Code or another coding agent? Open it in the folder: it reads `CLAUDE.md`
and `AGENTS.md`, and the prompts in [`../prompts/`](../prompts/README.md) take it through the
same steps.

## 7. Ship it

```sh
make image                            # the Docker image logbook:<version>
make dev-package                      # dist/logbook-<version>.pcapp, signed with a development key
```

Install the `.pcapp` from PlantCraft > Apps > Install from file. For a real installation you
sign with your own publisher key: [packaging.md](packaging.md) and [publishing.md](publishing.md).
