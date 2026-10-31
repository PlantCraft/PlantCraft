# vendor

Two packages of PlantCraft that are published on no index. PlantCraft View pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.95.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.95.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
fb337718): every app on SDK 0.95.0 vendors these same bytes.

## @plantcraft/ui 0.98.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.98.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.98.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
6132bca98cceba5a9b41d9f5b77fb971b82d788d6f6fb07080f789161a4ad469  plantcraft_sdk-0.95.0-py3-none-any.whl
d6240f3e33f0f6529505776885fec70d998452cdfa793f8a217034f9a0f0ca0b  plantcraft-ui-0.98.0.tgz
```
