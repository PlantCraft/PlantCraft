# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.93.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.93.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
9a11e118): every app on SDK 0.93.0 vendors these same bytes.

## @plantcraft/ui 0.97.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.97.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.97.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
d8be22e11de7a75a7c87a64b8277064372a98fe622103a3e70a2148073c6a501  plantcraft_sdk-0.93.0-py3-none-any.whl
62221b3d78f66ab6ce531f0821ae0cbdc21eb6a3582e773815c2880d71de25b9  plantcraft-ui-0.97.0.tgz
```
