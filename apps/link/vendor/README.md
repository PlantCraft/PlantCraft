# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Analytics pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.85.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.85.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
e105b4c): every app on SDK 0.85.0 vendors these same bytes.

## @plantcraft/ui 0.91.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.91.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.91.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
2912b08abb617cdc68913e010dfaf51ca3fbd765b18766ab27232c2d7efc7f7f  plantcraft_sdk-0.85.0-py3-none-any.whl
d6ffd66416bbd87f35688760d142c34726cd7fe76efb0f09ea2b8e7a3ba1df8a  plantcraft-ui-0.91.0.tgz
```
