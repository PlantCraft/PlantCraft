# vendor

Two packages of PlantCraft that are published on no index. PlantCraft View pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.90.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.90.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
865078b): every app on SDK 0.90.0 vendors these same bytes.

## @plantcraft/ui 0.93.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.93.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.93.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
a0a5e87c3969c976f0dc507865591f45a2dbd0d045e8ff101bf73f35b3aec40f  plantcraft_sdk-0.90.0-py3-none-any.whl
0fdf2e7634f005b9193b9d173eff6e6067394003c40b5adc0ec7256f5917208e  plantcraft-ui-0.93.0.tgz
```
