# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Historian pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.97.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.97.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
b67ecb4): every app on SDK 0.97.0 vendors these same bytes.

## @plantcraft/ui 0.101.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.101.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.101.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
94f3db7b1791a02546b3ff0bb9529e6d190ddc60c32cdfe9b3073c058aa50d71  plantcraft_sdk-0.97.0-py3-none-any.whl
227d2ac56c13261242a6248ac32e520085cb2a342045d89793e75cf814e3eb95  plantcraft-ui-0.101.0.tgz
```
