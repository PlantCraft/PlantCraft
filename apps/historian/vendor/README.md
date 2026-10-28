# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Historian pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.77.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.77.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
cc1e66c): every app on SDK 0.77.0 vendors these same bytes.

## @plantcraft/ui 0.85.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.85.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.85.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
275fe2baa995d9332fde3a6fe02935a392976f8aae0afe28d89c70b53b80ca18  plantcraft_sdk-0.77.0-py3-none-any.whl
01115b5bf04dbe79255870a394b26bd1b2ff3ab8661890254cbe7f8d900cda51  plantcraft-ui-0.85.0.tgz
```
