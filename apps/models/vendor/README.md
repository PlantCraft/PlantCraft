# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.106.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.106.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
4690f1f): every app on SDK 0.106.0 vendors these same bytes.

## @plantcraft/ui 0.111.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.111.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.111.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
22d032f58562d56a5e942d2b375d9ebadba57ee595bbdf070dd079934c7a0d9b  plantcraft_sdk-0.106.0-py3-none-any.whl
db4a8050b968d13a3ed286a3f31ff8f2ac794f106dab15a3be8c10c5fee9dc56  plantcraft-ui-0.111.0.tgz
```
