# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.99.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.99.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
739f4ed): every app on SDK 0.99.0 vendors these same bytes.

## @plantcraft/ui 0.104.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.104.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.104.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
638bb2737dbd8c5a730a9ae55265ac31866b008ebc97a380b106e0d5a3476d25  plantcraft_sdk-0.99.0-py3-none-any.whl
13f0cd1c328459bbfec28dd3ea127cd975946a9c2e8ed073bdac662a7ce03131  plantcraft-ui-0.104.0.tgz
```
