# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.84.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.84.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
4a587f4c): every app on SDK 0.84.0 vendors these same bytes.

## @plantcraft/ui 0.91.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.91.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.91.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
7dad1c4978c376d3b662f6f5e0a37285a71db4ba4c3f17b4f726c0360041ca62  plantcraft_sdk-0.84.0-py3-none-any.whl
1e3c5dbe828a9ca4307f487e2a4a0a7d3fe03846faec8a3b220efd5faf2cd875  plantcraft-ui-0.91.0.tgz
```
