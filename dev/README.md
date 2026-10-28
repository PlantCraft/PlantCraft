# Quick changes: preview first, ship later

A small interface change (a button's color, a label, a spacing) should show on the Mac mini's
suite (https://processcraft.company.local/) in seconds, not after tests, an image build, a pull request
and CI. These tools split the work in two:

| Step | What runs | Time |
|---|---|---|
| **Preview**, after each change | `dev/preview`: the working tree goes to the repository's `preview` branch; the Mac mini rebuilds the interfaces that changed and the open pages reload by themselves | 3 to 10 s |
| **Ship**, once for a batch | `dev/ship`: `make ci` in every part (platform, `apps/<app>`, `simulator`) with changes; then commit, pull request, merge; the Mac mini's CI deploys the new images | minutes |

A preview carries the **interface only** (`frontend/` of the platform and of each app, and the
shared frame in `ui/src`). A change to Python, the API or the database needs the ship step to be
seen. The `preview` branch runs no CI: the workflows run on pull requests and on main only.

## For agents: the loop

```sh
# edit frontend/, apps/<app>/frontend/ or ui/src, then, from the repository's root:
dev/preview                                      # the whole working tree, every app at once
```

Tell the person the change is on screen and keep going; do not run tests between quick changes.
When they say the batch is done (or before the session ends), ship it:

```sh
dev/ship                                         # make ci in each part that differs from main
# commit, push the branch, open and merge the pull request, as usual
dev/preview --clear                              # the Mac mini goes back to main
```

Never leave unshipped work only on `preview`: it is overwritten by the next preview and is not a
backup. The one `preview` branch is shared by every session; the last push wins.

## On the Mac mini: switch it on (once)

```sh
cd ~/processcraft-ci && git pull   # any clone of processcraft; first time: git clone https://github.com/PlantCraft/PlantCraft ~/processcraft-ci
dev/suite-dev on        # every app the suite runs; or name some: dev/suite-dev on linkcraft
dev/suite-dev status    # what each app shows (branch, commit, time of the build)
dev/suite-dev logs      # the builds, live
dev/suite-dev off       # back to the interfaces inside the images
```

Any clone works (the script only uses Docker and `gh`; the container keeps its own checkouts).
It needs Docker Desktop and the GitHub CLI signed in (`gh auth login`), as the CI runners do.
The first `on` takes a few minutes (`npm ci` per app); after that it survives reboots.

## How it works

- `suite-dev on` starts the `processcraft-dev` container (Node 22). Inside, `follow.sh` keeps one
  checkout of the repository (`~/PlantCraft/dev/src/processcraft`) on its `preview` branch, or
  main when there is none, and checks GitHub every 3 s (`INTERVAL`). Every app builds from its
  folder there, with the shared frame from `ui/src`.
- `watch.mjs` is each app's own `vite build` in watch mode: no minify, Plotly loaded as already
  built, `@plantcraft/ui` from source. A change rebuilds in about 2 s. It writes into the
  app's `frontend/dist` in that checkout, and the page polls `index.html` to reload itself when it changes.
- `dev.compose.yaml` (written by `on`, removed by `off`) mounts that `frontend/dist` read-only
  where the app's image keeps its interface (`/app/ui`, PlantCraft's `/app/frontend/dist`). The
  app's own server keeps serving it: same sign-in, same paths, same API. `suite-deploy` passes the
  file too, so a deploy from main keeps the preview mounted. `install.sh` does not: after an
  install or upgrade, run `dev/suite-dev on` again.
- A change to `dev/follow.sh` or `dev/watch.mjs` on processcraft's main (or preview) reaches the
  container by itself: it restarts with the new copy.

This is a development tool for the Mac mini only. The container reads GitHub with the token of
`gh auth token`; never run it on a client's server.

## SDK and ui versions: `dev/sdk-version`

A branch that changes `sdk/python` or `ui/` ships them as a new version, and parallel branches
would all pick main's next number. The number is taken only at merge, by the script:

```sh
dev/sdk-version          # merge origin/main, next free SDK/ui versions, build, vendor everywhere, commit
dev/ship                 # make ci of what changed; it also runs dev/sdk-version --check
# push, merge at once; put "SDK 0.73.0" (as printed) in the pull request's title
```

- Conflicts in vendored files, and conflicts whose two sides differ only in version numbers and
  hashes (pins, lock files, `__version__`), are taken from main and then rewritten. Any other
  conflict stops the script: resolve it, `git commit`, run it again.
- A package the branch does not change keeps main's version; one already above main's is kept.
- "SDK x" and "ui y" in the Markdown lines the branch adds (changelogs, devlog) move to the new
  numbers.
- If main takes another SDK before your merge, GitHub shows a conflict in the vendored wheels and
  `dev/sdk-version --check` fails: run `dev/sdk-version` again.
