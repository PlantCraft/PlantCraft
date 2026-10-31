# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.94.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.94.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
9e87ed4): every app on SDK 0.94.0 vendors these same bytes.

## @plantcraft/ui 0.99.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.99.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.99.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
a6fc0fa857013254367663a2dd76e13affcce7b6b0f79aa9268a53d4c2c44623  plantcraft_sdk-0.94.0-py3-none-any.whl
4ced4ba80001a51532ea60e13015d8e5b63896bb7a9a3d763157cc3aa2eae17e  plantcraft-ui-0.99.0.tgz
```
