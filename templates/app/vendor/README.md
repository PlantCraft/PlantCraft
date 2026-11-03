# vendor

Two packages of PlantCraft that are published on no index. StarterCraft pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.105.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.105.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
fec53a9): every app on SDK 0.105.0 vendors these same bytes.

## @plantcraft/ui 0.112.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.112.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.112.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
8a5f13d253a7fbdde269b615609c9e8b8b4627eefddd4e85d3c2eb5756cae368  plantcraft_sdk-0.105.0-py3-none-any.whl
c969fa9b7675e3929c5f8639f59c1229c7599ec9b062c902135f36397adcbfaa  plantcraft-ui-0.112.0.tgz
```
