# Publishing the suite

**Since 2026-10-29 the suite is developed in the open, in `PlantCraft/PlantCraft`.** Every
commit, branch, pull request and comment there is public. The repository it came from, with the
whole history of its first weeks, stays private and archived; `PlantCraft/PlantCraft` started from
one clean commit of it and took a second one, of the same kind, when development moved.

The gates below now check every change as well: the Security workflow's `secrets` job (gitleaks)
and its `words` job, which reads the words that must never be published from the repository
secret `BANNED_WORDS` and fails on any of them in the tree or in a pull request's commit messages.

`dev/snapshot` still builds one clean commit of a repository and checks it, for example
`PlantCraft/plantcraft-app-template`, the starting point for anyone who builds an app of their
own (`templates/app`). Creating repositories and making anything public stays the owner's
decision (AGENTS.md, section 9).

## Building the snapshot

```sh
BANNED_FILE=~/banned-words.txt dev/snapshot ~/snapshot     # PlantCraft.bundle and plantcraft-app-template.bundle
BANNED_FILE=~/banned-words.txt OWNER=PlantCraft REF=origin/main dev/snapshot ~/snapshot
```

For each repository the script:

1. takes the files of `REF` (default `origin/main`) and none of the history;
2. leaves out what is never published (`ci/macmini`, the owner's own build machine);
3. rewrites the links to the private repositories so they name the new owner, and turns the owner's
   own machine name into a neutral example host;
4. checks the gates below;
5. when every gate passes, makes one commit and writes `<repo>.bundle`. A bundle is a whole git
   repository in one file;
6. for PlantCraft, does the same with `templates/app` alone, as `plantcraft-app-template.bundle`
   (it stays in PlantCraft too, where `.github/workflows/template.yml` tests it against the
   current SDK and interface).

`REPORT.md` beside the bundles says what each gate found. The script exits non-zero if any
repository failed a gate, and it writes no bundle for that repository.

## The gates

| Gate | What fails it |
|---|---|
| What never goes out | A word of `BANNED_FILE`: the institutions, companies and private projects whose material may not be used, since only public information and methods go in the suite. The list is kept outside every repository, because naming them here would publish them. |
| Private links | Any reference to the private repositories' owner left after the rewrite, or to the development workspace (its shared folder and its private pages), and any link to a repository of the new owner that is not published (`PUBLISHED`, default `PlantCraft` and `plantcraft-app-template`), so the site's chat never cites a missing page. |
| Secrets | A finding of [gitleaks](https://github.com/gitleaks/gitleaks) with the default rules. `.gitleaks.toml` lists the test files whose made-up keys and tokens are expected. Without gitleaks the report says the gate was not checked. |
| License | A repository without `LICENSE`, or a `pyproject.toml` or `package.json` that declares no license. |

Third-party licenses are checked apart from the snapshot, on the installed dependencies:

```sh
.venv/bin/pip install pip-licenses && .venv/bin/pip-licenses --from=mixed
cd frontend && npx license-checker-rseidelsohn --production --summary
```

Every `package-lock.json` also records each package's license, so the frontends can be checked
without installing them. Each folder's `ATTRIBUTION.md` has a row for every direct dependency.

The dependencies are permissive (MIT, BSD, Apache-2.0, ISC), apart from the cases below:

- These are under MPL-2.0, used unmodified: `certifi`, `fqdn` (through Jupyter Server), Pyodide
  (Notebooks in the browser) and python-build-standalone's build scripts (the Python of the local
  Notebooks kit; CPython itself is under PSF-2.0).
- These are under LGPL-3.0, used as unmodified libraries: `asyncua` (OPC UA), `psycopg` (Historian),
  `ldap3` (corporate login).
- OpenModelica, in the Models runner image, is under OSMC-PL or GPL-3.0. It runs as a separate
  program and is never linked into the app (`deploy/runner/Dockerfile` in Models). The FMUs that
  Analytics carries link the OpenModelica runtime under the OSMC-PL's BSD-new option
  (`apps/link/ATTRIBUTION.md`).
- Documents' embedding model, multilingual-e5-small, is under MIT and is downloaded at build.
- The fonts are under OFL-1.1.
- The images are built on Debian-based Python images, whose system packages include GPL programs
  (bash, coreutils and others). An offline bundle redistributes them, so its release notes must point
  to the Debian sources of the same release (`snapshot.debian.org`).

The libraries by area, with their versions, are in [the stack](en/stack.md).

All of these allow an Apache-2.0 suite. The LGPL and GPL components keep their own license and
notices in the images that carry them.

## Pushing a bundle

This is done by the owner, once the new repository exists and is still private:

```sh
git clone PlantCraft.bundle PlantCraft && cd PlantCraft
git remote set-url origin https://github.com/PlantCraft/PlantCraft.git
git push -u origin main
```

Then, still private:

- set the repository variables and secrets CI needs;
- check that CI is green;
- check that the release workflow can sign with the release key on the build machine.

Make the repositories public only after that.
