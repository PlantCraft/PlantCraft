# vendor

Two packages of PlantCraft that are published on no index. StarterCraft pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.103.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.103.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
d441e05): every app on SDK 0.103.0 vendors these same bytes.

## @plantcraft/ui 0.107.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.107.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.107.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
5be2231ec937cb99a45aaf269aca58aacd2418d52f3c06b459d9e2061578d196  plantcraft_sdk-0.103.0-py3-none-any.whl
727f1932f6412526464287256871f349879401b90c263dc76b7ac2c9d878560d  plantcraft-ui-0.107.0.tgz
```
