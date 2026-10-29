# vendor

Two packages of PlantCraft that are published on no index. StarterCraft pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.78.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.78.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
ac27dc4): every app on SDK 0.78.0 vendors these same bytes.

## @plantcraft/ui 0.88.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.88.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.88.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
f910cd3a566e967807e8c8c5c13163afa4906f45111e6cafb966b8664933aa74  plantcraft_sdk-0.78.0-py3-none-any.whl
9e7877cc4e613cc00ef4efbe64e20c07f9c564ac08f7a7abe03d39051ad9ad04  plantcraft-ui-0.88.0.tgz
```
