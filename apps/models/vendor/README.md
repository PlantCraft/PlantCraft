# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.95.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.95.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
8459acf9): every app on SDK 0.95.0 vendors these same bytes.

## @plantcraft/ui 0.99.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.99.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.99.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
7f7fa1e64e4c5dd65e1d019204160f216497df654d12a15caef9941527121e1a  plantcraft_sdk-0.95.0-py3-none-any.whl
0acfefff6101e1110e77650cc8413aea3f220d55899e1f68bcae682ba118d9d7  plantcraft-ui-0.99.0.tgz
```
