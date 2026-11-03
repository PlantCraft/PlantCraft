# Packaging

An installation receives your app as one signed file, `<id>-<version>.pcapp`: the manifest
(from `app.toml`), the Docker image and its SBOM, signed with your publisher key. PlantCraft
checks the signature and every hash, shows the administrator what the app may do, and runs it
under the suite's container rules.

## `app.toml`, key by key

`app.toml` is the single source of the app's metadata. The launcher card, the Apps page, the
package, the image labels and `/api/meta` all read it; `make ci` checks it.

### `[app]`

| Key | Rule |
|---|---|
| `id` | `[a-z][a-z0-9]{2,30}`; the Python package, the image and the settings prefix (`ID_*`). Never changes once installed somewhere |
| `name` | `<Name>Craft` (the names `PlantCraft <Name>` are the suite's own) |
| `version` | Semantic version, equal to `pyproject.toml` and `__version__` |
| `category`, `summary`, `description` | What the Apps page shows: one category, one line, one paragraph |
| `publisher` | The name of the key that signs the package; the installation must trust it |
| `license` | The code's licence (SPDX id) |
| `homepage` | Optional |
| `mark` | The app's mark in the suite's icon family; your id gets a neutral letter tile |

### `[runtime]`

| Key | Rule |
|---|---|
| `prefix` | `/<id>/`; not one of PlantCraft's own paths, not another installed app's |
| `port` | The port inside the container (above 1024); optional |
| `uid` | The container user and group (10002 to 65533); optional, from the id when left out |
| `health` | `/healthz` |
| `image` | Equal to the id; the image is `<id>:<version>` |

### `[requires]`

| Key | Rule |
|---|---|
| `processcraft_api` | The API v1 range the app works with (`">=1.0"`) |
| `sdk` | The SDK version in `vendor/` (moved by `dev/revendor`) |
| `asset_types`, `roles` | The asset types the app works on and the signal roles it needs on each; `[]` and `{}` for none |

### `[permissions]`

Shown to the administrator before installing, and held to every API v1 route: the app key can do
exactly this and nothing else.

| Key | Values |
|---|---|
| `read` | `assets`, `signals`, `series`, `results`, `events`, `runs`, `schedules`, `people`, `knowledge` |
| `write` | `audit`, `results`, `events`, `runs`, `schedules`, `series`, `notifications`, `knowledge`, `compute`, `llm` |
| `plant_write` | Always `false` |
| `outbound` | Always `[]` |

Declare only what the app uses: the fake PlantCraft in the tests fails on anything else, and an
administrator is more likely to install an app that asks for little.

### `[publishes]`, `[consumes]`, `[contributes]`

What the app shares with other apps (results, events, derived series) and what it adds to
PlantCraft's own screens (search, widgets, Desk, language model uses, references). The template
declares none; each recipe in [recipes/](recipes/README.md) shows the lines to add.

### `[backup]`, `[suggests]`

What the suite's backup takes from the data folder ([data.md](data.md)); the asset types offered
at install.

### Coming with the app package format (PlantCraft PR #179)

The PlantCraft release after 0.6.0 is planned to add these keys. They are commented out at the
end of the template's `app.toml`, because the SDK in `vendor/` refuses keys it does not know yet.
Uncomment them when you move to that SDK.

| Key | Means |
|---|---|
| `[app] source` | `"open"` (the default) or `"closed"`: a compiled image that needs a licence |
| `[app] languages` | The languages the app is translated to (`["en", "pt-BR"]`); `"en"` is required and each other one needs its catalogs in `frontend/src/locales/` and `src/<id>/locales/` |
| `[requires] platform` | The PlantCraft versions the app installs on (`">=0.7,<0.9"`); PlantCraft refuses an install outside it |
| `[tested] platform` | The PlantCraft versions the app was tested on; written at build time, never by hand. PlantCraft only warns when the version it runs is not listed |
| `[license] required`, `grace_days` | Closed apps: the installation needs a signed `.pclicense` from you; `grace_days` (0 to 90) it may run without one |

Until that release, the standard and these keys may still change; PlantCraft's
`docs/app-package.md` is the reference once it is merged.

## The image

```sh
make image                       # starter:<version>
make image BUILD_CA=/path/ca.pem # behind a proxy that inspects TLS
```

The `Dockerfile` builds in three stages: the interface (Node), the wheels (Python), and the
runtime image. It installs only hashed dependencies (`deploy/requirements.lock`), runs as the
`uid` of `app.toml`, has a read-only root and writes only to `/data` and `/tmp`, and carries the
labels PlantCraft reads. The SBOM is written into the image at build (`/app/sbom.json`).

A new Python dependency: add it to `pyproject.toml` and `deploy/requirements.in`, run
`make lock` (needs `uv`), and say why in the commit. A new npm dependency: `npm install` in
`frontend/` and commit `package-lock.json`. Every dependency gets a row in `ATTRIBUTION.md`, and
its licence must be permissive (MIT, BSD, Apache-2.0, ISC).

## The package

### For a development PlantCraft

```sh
cd ../PlantCraft && make dev-publisher && cd -   # once: a development key a dev stack trusts
make dev-package                                 # dist/starter-<version>.pcapp
```

`app.toml` `publisher` must be `"Dev Publisher"` for this key (the template's default). Install it
from PlantCraft > Apps > Install from file.

### For a real installation

Once, make your publisher key pair with PlantCraft's tool and keep the private key outside every
repository:

```sh
python3 ../PlantCraft/plantcraft/apps/package.py keygen --name "Acme Tools" --out-dir ~/secure/keys
```

Set `publisher = "Acme Tools"` in `app.toml`. Give the installation's administrator the public key
(`acme-tools.pub`): it goes in the installation's `trusted-publishers/` folder. Then, for each
release:

```sh
make package PUBLISHER_KEY=~/secure/keys/acme-tools.key
# dist/starter-<version>.pcapp and dist/starter-<version>.pcapp.sha256
```

`make package` builds the image, takes its SBOM and calls PlantCraft's `deploy/package.sh`, which
needs a PlantCraft checkout (`PLANTCRAFT_DIR`, default `../PlantCraft`).

## Installing

On the installation, an administrator:

1. opens PlantCraft > Apps > **Install from file** and picks the `.pcapp` (or runs
   `./install.sh --add starter-0.1.0.pcapp` on the server);
2. reads the publisher, the permissions and the SBOM, and confirms;
3. gives people access to the app under Users.

PlantCraft gives the app its app key, starts its container on the suite's network (no published
port, read-only root, no capabilities, limits on CPU and memory) and adds its route to the proxy.
An update is the same flow with a newer version; the previous one is kept for rollback. Removing
the app keeps its data folder.
