# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.93.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.93.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
057deef): every app on SDK 0.93.0 vendors these same bytes.

## @plantcraft/ui 0.97.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.97.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.97.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
aa4f656ff68c5a5bed49ce313a50af9484215ef6cf6266a6e62a10f49b9a1d37  plantcraft_sdk-0.93.0-py3-none-any.whl
62221b3d78f66ab6ce531f0821ae0cbdc21eb6a3582e773815c2880d71de25b9  plantcraft-ui-0.97.0.tgz
```
