# vendor

Two packages of PlantCraft that are published on no index. StarterCraft pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.106.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.106.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
5f15578): every app on SDK 0.106.0 vendors these same bytes.

## @plantcraft/ui 0.111.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.111.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.111.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
9d866da4d745cf818bf099e6e17f31d57ff65c74da439241cacb01111afc03eb  plantcraft_sdk-0.106.0-py3-none-any.whl
db4a8050b968d13a3ed286a3f31ff8f2ac794f106dab15a3be8c10c5fee9dc56  plantcraft-ui-0.111.0.tgz
```
