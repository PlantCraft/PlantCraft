# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.85.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.85.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
955eed5): every app on SDK 0.85.0 vendors these same bytes.

## @plantcraft/ui 0.91.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.91.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.91.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
31650df0db130d3551bfd747eb6ed8e6163fa54373a9cbc3cf93239a95fb1480  plantcraft_sdk-0.85.0-py3-none-any.whl
a8442ac78f1e82dfc2d67ca33b07075a00b596707b5d309fb9f46b106471d86f  plantcraft-ui-0.91.0.tgz
```
