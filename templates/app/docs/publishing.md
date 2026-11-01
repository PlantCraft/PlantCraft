# Publishing

## Your repository

An app of your own lives in your own repository, made from this template. The PlantCraft
repository holds only the suite's official apps. Keep in yours:

- the code, the tests and this documentation, with `make ci` green on every push (GitHub runs it,
  `.github/workflows/ci.yml`);
- `SPEC.md` with every public source the app relies on (standards, public manuals, papers), and
  `ATTRIBUTION.md` with every third-party library or asset;
- no client or employer data, names, tags or hostnames, not even as examples;
- never a private key (the publisher key, an app key) in the repository.

## Versions

The app follows [semantic versioning](https://semver.org): `MAJOR.MINOR.PATCH`.

| Change | Version |
|---|---|
| A fix that changes nothing a person or another app relies on | PATCH (`0.1.1`) |
| Something new: a field, a page, a route | MINOR (`0.2.0`) |
| Something removed or changed in a way that breaks a user or another app | MAJOR (`1.0.0`); before 1.0, MINOR |

The version is written in three places that `make ci` holds equal: `app.toml` `[app] version`,
`pyproject.toml` `version` and `__version__` in `src/<id>/__init__.py`.

## A release

1. Move the lines under `## [Unreleased]` in `CHANGELOG.md` to `## [x.y.z] - <date>`
   ([Keep a Changelog](https://keepachangelog.com): Added, Changed, Fixed, Removed).
2. Change the version in the three places above. A table change since the last release is a
   step in its store's `MIGRATIONS` ([data.md](data.md)).
3. `make ci` and `make e2e` green.
4. `make package PUBLISHER_KEY=...` ([packaging.md](packaging.md)).
5. Install the package on a test PlantCraft, then upgrade an installation of the previous version
   and check its data is still there.
6. Tag the commit (`git tag v0.2.0 && git push --tags`) and make a GitHub release with the
   `.pcapp` and its `.sha256`.

Give the administrators who install it the `.pcapp`, its SHA-256 and your public key. A plant
on an isolated network installs from the file; nothing needs the internet.

## Keeping up with PlantCraft

The SDK and `@plantcraft/ui` are published on no package index: they come from the PlantCraft
repository and live in `vendor/`, pinned and hashed. To move to a newer PlantCraft release:

```sh
cd ../PlantCraft
git fetch --tags && git checkout v<release>      # the release your users run
make sdk-wheel ui-package                         # builds both packages into dist/
dev/revendor ../<your-app>                        # copies them into vendor/ and moves every pin
cd ../<your-app> && make ci
```

`dev/revendor` changes `vendor/`, `pyproject.toml`, `app.toml` `[requires] sdk`, the Makefile, the
Dockerfile and `frontend/package.json` and its lock. Read the PlantCraft changelog for what
changed in the SDK and the interface, fix what `make ci` reports, then release.

Keep the app working on the PlantCraft version your users run. PlantCraft tests each release's
API v1 against the SDK of the release before it, so an app built for an older PlantCraft keeps
working on a newer one; its changelog names any change to API v1.

## Open and closed apps

The template is open source (Apache-2.0), and so is an app made from it, unless you choose
otherwise: the licence of your app is yours to pick, in `LICENSE`, `app.toml` `license` and
`pyproject.toml`.

A **closed** app (compiled, sold with a licence per installation) depends on the app package
format of PlantCraft PR #179, planned for the release after 0.6.0: `[app] source = "closed"`, a
compiled image and a signed `.pclicense` that the administrator adds in PlantCraft > Apps >
Licences. Until it is released, every app is installed as open. A closed app's source must live
in a private repository: code in a public repository, or in its history, is public.

## The PlantCraft catalog

PlantCraft can install apps from an online catalog, off by default (an administrator turns it
on). Listing your app there is not open yet; until then, share the `.pcapp` directly.
