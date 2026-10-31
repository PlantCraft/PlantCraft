# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Documents pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.83.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.83.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
d2125ac): every app on SDK 0.83.0 vendors these same bytes.

## @plantcraft/ui 0.90.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.90.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.90.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
3bcc1d6be4fd38f8ba28a1a5b93c6c80e631a9c4d8d513cfec81a8d186f3ec31  plantcraft_sdk-0.83.0-py3-none-any.whl
66fed2821b0b258c0d5efa991a389b0fcea06c4b139ad5a2260fd3e594bfa929  plantcraft-ui-0.90.0.tgz
```
