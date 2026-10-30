# Deploys on the Mac mini

The repository is public, so GitHub's own runners run its tests and checks at no cost. The Mac
mini keeps one job: it makes its local suite (`~/PlantCraft`) follow `main`. A few minutes after a
merge, the app's new version is running there.

## What runs where

| When | Job | Where |
|---|---|---|
| Pull request | `Lint` (ruff in every Python folder, about a minute) and `Security` | GitHub |
| Push to main (a merge) | `deploy`: rebuild the image, recreate only this app's container, data kept; it does not wait for the tests | Mac mini |
| Main at about 09:00, 13:00, 17:00 and 21:00 Brasília | each workflow's tests and browser journeys (e2e), only if its folder changed since its last green run (`ci/since-green`) | GitHub |
| Main at about 06:00 Brasília | `Security` | GitHub |
| By hand (Actions > the workflow > Run workflow) | the tests and e2e at once, then the deploy | GitHub, then the Mac mini |
| By hand with "hosted" ticked | also the container jobs: docker smoke, isolation + bundle, PostgreSQL, FMU rebuild, the Simulator on macOS/Windows | GitHub |
| Push to main while `MACMINI_DEPLOY` is off | the container jobs | GitHub |

The platform and every app live in this one repository, each with its own workflow
(`.github/workflows/ci.yml` for the platform, the SDK and the shared ui; `link.yml`,
`historian.yml`, `view.yml`, `alarms.yml`, `models.yml`, `documents.yml`, `simulator.yml` for
`apps/<app>` and `simulator`; `template.yml` for the app template). A workflow runs only when its
folder changes, so a change to one app deploys that app alone. `concurrency` cancels a pull
request's run that a newer push replaces, and changes to documentation only (`*.md`, `docs/`) run
nothing.

**Tests on main a few times a day.** A pull request runs only Lint and
Security, and its author runs `make ci` of every folder the change touches (`dev/ship`) before
merging; that is the gate. The full tests and e2e run on main four times a day, and by hand when
needed (`gh workflow run ci.yml -R PlantCraft/PlantCraft`, or the app's workflow). A merge is
deployed to the Mac mini at once, so the owner sees it there within minutes, tested or not. When a
scheduled run fails, the change that broke it is found among the merges since the last green run
and fixed or reverted at once. Pull requests still start each workflow (its jobs are skipped), so
the status checks a ruleset may require are reported.

**A public repository and a machine of our own.** A pull request's workflow runs from the pull
request's own files, so a stranger's fork could edit one to ask for the Mac mini. Three things
keep it off: the test jobs name GitHub's runners (`TEST_RUNNER` may name another, never the Mac
mini); every runner here refuses, in its job-started hook (`ci-slot-acquire.sh`), any job that is
not main's (a push, the schedule or a run by hand, all of which need write access); and
`setup.sh` makes every outside contributor's workflow run wait for a maintainer's approval. The
deploy jobs read no secret.

The repository variable `MACMINI_DEPLOY=true` turns on the deploy and moves the container jobs to
manual. `gh variable set TEST_RUNNER --body <label> -R PlantCraft/PlantCraft` sends the test jobs
to another GitHub-hosted runner; `gh variable delete TEST_RUNNER -R PlantCraft/PlantCraft` brings
them back to `ubuntu-latest`.

## Set up (once, on the Mac mini)

You need Docker Desktop running and the GitHub CLI, signed in as the repositories' owner:

```bash
brew install gh && gh auth login
git clone https://github.com/PlantCraft/PlantCraft ~/plantcraft-ci   # any clone of the repository
cd ~/plantcraft-ci
ci/macmini/setup.sh
```

`setup.sh` builds the runner image (Ubuntu 24.04, the official `actions/runner` checked against
its published SHA-256, the Docker CLI). It then starts the repository's runners, one per CI
slot (up to three, see below), removes the per-app runners of the repositories the apps came
from, and sets `MACMINI_DEPLOY`. A runner still registered for the former private repository is
registered again for this one. On a public repository it also makes outside contributors' workflow
runs wait for approval (see above). You can run it again at any time. Docker Desktop restarts the
runners after a reboot.

- Status: `docker compose -f ci/macmini/compose.yaml ps`
- Logs: `docker compose -f ci/macmini/compose.yaml logs -f processcraft`
- Deploys off (the container jobs back on GitHub): `ci/macmini/setup.sh --off`. While the Mac
  mini is offline, deploy jobs wait in the queue (for up to 24 h), so use `--off` before a long
  shutdown.

The suite is expected in `~/PlantCraft` (or `~/ProcessCraft`, where it was installed before the rename). For another prefix, run
`SUITE_DIR=/path ci/macmini/setup.sh`.

## Memory: one job at a time per slot

All runners share Docker Desktop's memory. Each runner container is capped at 3 GB, and a job
first waits for one of `CI_SLOTS` shared slots (`ci-slot`, the runner's job-started and
job-completed hooks). `setup.sh` sizes `CI_SLOTS` from Docker Desktop's memory: 4 GB is kept
for the suite, then one slot per 3 GB, between 1 and 3, and as many runners. Other jobs queue
instead of running out of memory. For more parallel jobs, give Docker Desktop more memory
(Settings > Resources) and run `setup.sh` again, or set `CI_SLOTS=2 ci/macmini/setup.sh`.

## How the deploy works

The runner mounts Docker Desktop's socket and the suite's folder at the same path. `suite-deploy`
takes the image `make image` just built and tags it with the name the suite's compose file uses
for that service, for example `linkcraft:0.1.0`. It then runs `docker compose up -d --no-deps`
for that service only and waits for its health check. The suite's `.env`, its volumes and the
other apps stay as they are. An app the suite does not run (its profile is off) is skipped.

A container is recreated only when its content changed. The build's commit and time are labels,
written last in each Dockerfile, so a commit that does not touch an image rebuilds it from the
cache with the same layers, and `suite-deploy` leaves that container running. This matters most
for the proxy: every route of the suite goes through it. While a server restarts, the proxy keeps
dialling it (up to 60 s for PlantCraft, 15 s for the apps) instead of answering 502, so a page
opened meanwhile loads slower instead of failing. Each push to main gets its own test run
(and its own e2e result); deploys of one app run one at a time, and a newer deploy waiting
replaces an older one waiting, so pushes close together still deploy once or twice. Every deploy job runs the script
from its own checkout, so a change to it applies without rebuilding the runner, and the deploy
hold of a soak (`$SUITE_DIR/data/deploy-hold`) holds every app.

After PlantCraft's own deploy, `notebook-kits` builds the Notebooks kits (Windows, macOS, Linux;
about 2 minutes, 450 MB) into `$SUITE_DIR/data/processcraft/notebook-kits`, which PlantCraft reads
at `/data/notebook-kits`, but only when what makes them changed (`build_kit.py --version`). The
downloads stay in the runner's cache between deploys, and backups leave the folder out. People
see the kit once an administrator turns it on in Setup › Notebooks.

A push deploys only the folders it changed. To bring one app up to main by hand, run its
workflow from the Actions tab (Run workflow on main): a manual run deploys too.

The images are built natively for arm64, so they no longer need Rosetta. Running the
`install.sh` of a new bundle still works as before: it installs the bundle's own images over
the top.

## Quick interface previews

For a small interface change, waiting for CI and a deploy is too slow. `dev/suite-dev on` makes
the apps here serve their interface straight from the repository's `preview` branch, rebuilt a
few seconds after every push, and `suite-deploy` keeps that in place. See `dev/README.md`.
