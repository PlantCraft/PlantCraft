# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Historian pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.103.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.103.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
e5d1132): every app on SDK 0.103.0 vendors these same bytes.

## @plantcraft/ui 0.107.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.107.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.107.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
e4257b0d05d0f36891517b813362f2bb019c2627f09c6af3d2970cc171b94b4c  plantcraft_sdk-0.103.0-py3-none-any.whl
c07e1134745cae065fe0d5f0f2c7af5f5b2f9fc33611a973acbd7b1ecfdcac11  plantcraft-ui-0.107.0.tgz
```
