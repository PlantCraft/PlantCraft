# App packages (`.pcapp`)

How an app of the suite is packaged, signed, checked and installed. What an app is, its
`app.toml`, its image and its runtime settings are in [app-standard.md](app-standard.md)
(sections 4, 7 and 8); this file is the package format and the installer behind the Apps page.
The code is `plantcraft/apps/package.py` (format and checks, standard library plus
`cryptography`), `plantcraft/apps/installer.py` (the installer service) and
`plantcraft/apps/manager.py` (what the Apps page does).

## 1. The file

`<id>-<version>.pcapp` is a tar (optionally gzip-compressed) of exactly four regular files:

| Member | What it is | Limit |
|---|---|---|
| `manifest.json` | the app's `app.toml` as JSON, plus `format` and `files` | 64 KiB |
| `manifest.sig` | Ed25519 signature of the exact bytes of `manifest.json`, base64 | 1 KiB |
| `sbom.spdx.json` | SPDX JSON SBOM of the image | 16 MiB |
| `image.tar` | `docker save` of one image tagged `<runtime.image>:<app.version>` | `PLANTCRAFT_APP_MAX_MB` (default 4096) |

Anything else in the tar refuses the whole package: other names, links, folders, devices,
repeated members, a member larger than its limit. The tar is read as a stream and nothing is
extracted by name; `image.tar` and the SBOM are copied to a private folder while they are hashed,
so what is loaded is exactly what was checked.

## 2. The manifest

```json
{
  "format": 1,
  "app": {"id": "linkcraft", "name": "PlantCraft Analytics", "version": "0.1.0", "category": "...",
          "summary": "...", "description": "...", "publisher": "PlantCraft",
          "license": "Apache-2.0", "homepage": "", "mark": "linkcraft"},
  "runtime": {"prefix": "/link/", "port": 8140, "uid": 10012, "health": "/healthz",
              "image": "linkcraft"},
  "requires": {"processcraft_api": ">=1.0", "sdk": "0.2.0", "asset_types": ["loop"],
               "roles": {"loop": ["pv", "op"]}},
  "permissions": {"read": ["assets", "signals", "series", "results"],
                  "write": ["audit", "results", "events", "runs", "schedules"],
                  "plant_write": false, "outbound": []},
  "publishes": {"results": [{"kind": "loop_health", "subject": "asset:loop"}],
                "events": ["finding.opened", "finding.closed"]},
  "consumes": {"results": [{"kind": "datacraft.signal_quality", "subject": "signal"}]},
  "suggests": {"asset_types": ["loop"]},
  "files": {"image.tar": {"sha256": "...", "size": 123},
            "sbom.spdx.json": {"sha256": "...", "size": 456}}
}
```

`[app]`, `[runtime]` and `[permissions]` are required; unknown sections or keys refuse the
package (there is no `environment`, `volumes` or `ports`: the installer sets those). Checks:

- `id`: `[a-z][a-z0-9]{2,30}`, not `processcraft`, `proxy`, `installer`, `plantcraft`, `simcraft`, `api`,
  `app`, `apps`. `version`: `1.2.0` or `1.2.0-rc.1`.
- `publisher`: a name whose key is `deploy/trusted-publishers/<slug>.pub`, the slug being the
  name in lower case with other characters turned into `-` (`Acme Tools` -> `acme-tools.pub`; PlantCraft keeps its first key, `processcraft.pub`).
- `runtime.image` equals the id; the image is `<id>:<version>` and `image.tar` must tag that and
  nothing else (never another app's or the suite's image).
- `prefix`, `port`, `uid`: an app listed in the suite table (app-standard.md, section 7) must
  use exactly its row; any other app may use none of the table's values, and at install none may
  be used by another installed app. Prefixes of PlantCraft's own pages (`/api/`, `/assets/`,
  `/apps/`, `/login/`, `/plant/`, `/data/`, `/settings/`, `/help/`, ...) are refused.
  `uid` is 10002 to 65533.
- `permissions.read` from `assets`, `signals`, `series`, `results`, `events`;
  `permissions.write` from `audit`, `results`, `events`, `runs`, `schedules`.
  `plant_write` must be `false` and `outbound` must be `[]`.
- Text has no control characters and stays within its length.
- `backup` (optional): `sqlite`, `files` and `skip`, paths inside the app's data folder.
- `contributes` (optional) and `publishes.series`: what the app adds to PlantCraft
  ([app-standard.md](app-standard.md), section 4b). Here only their shape is checked (tables of
  the known names, `queue` true or false, 64,000 bytes at most together); the SDK checks each
  table in full in the app's CI and PlantCraft again when the running app sends them. The page
  shows them as "What it adds to PlantCraft".

The Apps page shows the summary, description, publisher and key id, version, category, licence,
prefix, port and uid, every permission, and the SBOM's components before the administrator
confirms.

## 3. Building and signing

From any repository, with `docker`, `python3` and `cryptography`:

```bash
# Once per publisher: a key pair. Keep the .key outside every repository.
python3 plantcraft/apps/package.py keygen --name processcraft --out-dir ~/secure/keys
# Per release: build the image, then the package (SBOM from syft when --sbom is omitted).
docker build -t linkcraft:0.1.0 .
deploy/package.sh --app app.toml --key ~/secure/keys/processcraft.key --sbom sbom.spdx.json --out dist/
# dist/linkcraft-0.1.0.pcapp and dist/linkcraft-0.1.0.pcapp.sha256
python3 plantcraft/apps/package.py verify --trusted deploy/trusted-publishers dist/linkcraft-0.1.0.pcapp
```

From another repository, point `PLANTCRAFT_PACKAGE_PY` at a checkout's
`plantcraft/apps/package.py` (or copy that one file). For development,
`make dev-publisher` writes `keys/dev-publisher.key` and puts its public key in
`deploy/trusted-publishers/dev-publisher.pub`; both are ignored by git and `deploy/bundle.sh`
never ships a `dev*` key.

## 4. Online catalog

A folder served over HTTPS with the packages, `index.json` and `index.json.sig`:

```bash
python3 plantcraft/apps/package.py index --key ~/secure/keys/processcraft.key \
    --publisher processcraft --out-dir site/ site/*.pcapp
```

Off by default. It works only when `PLANTCRAFT_APP_CATALOG_URL` is set on the server **and** an
administrator turns it on in the Apps page (audited, `app.catalog.switch`). The index is checked
against the trusted publishers, each download against the size and SHA-256 in the index and then
like an uploaded file. Downloads never leave the catalog's address.

## 5. Install, update, roll back, remove

```text
Apps page --upload/download--> PlantCraft: verify, show, wait for confirm
          --confirm--> data/app-requests/<id>.json + <id>.pcapp (+ new app key)
installer (uid 10005, no network, Docker socket): verify again with its own trusted keys,
          docker load, check the image id, write data/installer/apps/<id>/compose.json and
          data/installer/routes/<id>.caddy, start app-<id>, recreate the proxy,
          write data/installer/status/requests/<id>.json
PlantCraft: read the outcome, update the list, audit it
```

- The installer never trusts PlantCraft's check: it reads the trusted keys from its own
  read-only mount. A failed start puts the previous compose file and route back.
- The app's service follows section 7 of the standard: image `<id>:<version>`, user `uid:uid`,
  read-only root, `/tmp` tmpfs, `cap_drop: ALL`, `no-new-privileges`, `pull_policy: never`,
  `apps` network only, no published port, limits (2 CPUs, 2 GB, 512 processes), and only the
  settings `PLANTCRAFT_URL`, `PLANTCRAFT_APP_KEY_FILE` (`/run/secrets/<id>_app_key`),
  `<ID>_ROOT_PATH`, `<ID>_DATA_DIR` (`/data`, the folder `data/apps/<id>`), `<ID>_HOST`,
  `<ID>_PORT`.
- Every installed app gets an app key at its first install from the page (kept on upgrades,
  revoked at uninstall). An app added with `install.sh --add` has none until an administrator
  clicks "Give it an app key".
- Updating is the same flow with a newer version; the previous version's manifest, signature and
  image stay, and rollback re-checks that signature and the image id before using them.
- Uninstall stops the app and removes its route and key; `data/apps/<id>` is kept.
- External apps (admin only) are only recorded: a name, an address, an optional version, a
  health check, a new app key shown once, and the "external" mark because their code was not
  checked.

Everything is audited: `app.package.verified` / `rejected`, `app.install.request`,
`app.catalog.download`, `app.catalog.switch`, `app.external.register` / `remove`,
`app.uninstall.request`, `app.rollback.request`, `app.key.request`, `app_key.create`, and the
installer's outcomes `app.install`, `app.uninstall`, `app.rollback`, `app.set_key`.

From the command line on the server (same checks, same code, through the installer image):

```bash
./install.sh --add linkcraft-0.1.0.pcapp
./install.sh --remove linkcraft
```

## 6. Folders

| Path (install folder) | Owner | Who reads it |
|---|---|---|
| `trusted-publishers/*.pub` | admin | PlantCraft and installer, read-only |
| `data/app-requests/` | PlantCraft (10001, 0750) | installer (group 10001), read-only |
| `data/installer/` | installer (10005) | PlantCraft read-only; the proxy reads `routes/` |
| `data/installer/secrets/<id>/app-key` | the app's uid, 0400 | that app only |
| `data/apps/<id>/` | the app's uid, 0700 | that app only (`/data`) |

To switch installs off: `PLANTCRAFT_APP_INSTALL=off` and leave out the `installer` service
(see security-guide.md, section 6).
