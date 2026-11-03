# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Analytics pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.105.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.105.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
42650d4): every app on SDK 0.105.0 vendors these same bytes.

## @plantcraft/ui 0.110.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.110.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.110.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
8a5f13d253a7fbdde269b615609c9e8b8b4627eefddd4e85d3c2eb5756cae368  plantcraft_sdk-0.105.0-py3-none-any.whl
c65cb9c4539df2cca814addbb27ea64ea7bcea9d33e1f63b91feee11f83f9c2f  plantcraft-ui-0.110.0.tgz
```
