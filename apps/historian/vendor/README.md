# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Historian pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.81.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.81.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
845477d): every app on SDK 0.81.0 vendors these same bytes.

## @plantcraft/ui 0.90.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.90.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.90.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
d60f16d5453471d7d59342e2bcd37ddc293744babe1716bdc87c0fa02ed7af1b  plantcraft_sdk-0.81.0-py3-none-any.whl
e822c3d0914cb0bd073b1af0a3791a8791a3502eea7915beca5afaa677a1bafb  plantcraft-ui-0.90.0.tgz
```
