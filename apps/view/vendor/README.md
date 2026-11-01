# vendor

Two packages of PlantCraft that are published on no index. PlantCraft View pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.97.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.97.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
02776b8): every app on SDK 0.97.0 vendors these same bytes.

## @plantcraft/ui 0.102.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.102.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.102.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
3962d573c3b0b03195fef2ff70f63192b45686dea9773db538bb4a17bfa0dfd3  plantcraft_sdk-0.97.0-py3-none-any.whl
bd7d34139bd69b2ec810c3a865e5837e8b3e7a36fe6a433238d107f2e98ec5e8  plantcraft-ui-0.102.0.tgz
```
