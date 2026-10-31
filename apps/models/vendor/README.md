# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.88.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.88.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
1f5ee50): every app on SDK 0.88.0 vendors these same bytes.

## @plantcraft/ui 0.92.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.92.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.92.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
8d2cfa2366a876c0f99101790db2ff7662307e9c43ba144f916dbdb6166746d8  plantcraft_sdk-0.88.0-py3-none-any.whl
8a31e50197c31b5451e14ba2879704df464df98f867bf9ab04933a808770e7e6  plantcraft-ui-0.92.0.tgz
```
