# vendor

Two packages of PlantCraft that are published on no index. StarterCraft pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.102.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.102.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
9531d88): every app on SDK 0.102.0 vendors these same bytes.

## @plantcraft/ui 0.106.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.106.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.106.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
a9b07c8c1a2e3d74d4b6219780e4b251fdf92dc8f1cf6fd7e1c60af347e40c23  plantcraft_sdk-0.102.0-py3-none-any.whl
6619d0bcf0648a59bd50aa5fce3093853c1849b32e156fe9b0607f6c3337a0e6  plantcraft-ui-0.106.0.tgz
```
