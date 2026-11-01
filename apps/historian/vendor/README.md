# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Historian pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.96.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.96.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
d6bf0ee): every app on SDK 0.96.0 vendors these same bytes.

## @plantcraft/ui 0.100.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.100.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.100.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
86a6d5296abc6bb23d92632378ad843ed8db380d1d1b9630a973e6e976021c8e  plantcraft_sdk-0.96.0-py3-none-any.whl
eb481a6f0c9c3d0e204b4423787d96ee05027f1b63924dfd18d681136c4e688f  plantcraft-ui-0.100.0.tgz
```
