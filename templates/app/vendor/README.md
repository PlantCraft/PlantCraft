# vendor

Two packages of PlantCraft that are published on no index. StarterCraft pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.92.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.92.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
9656077): every app on SDK 0.92.0 vendors these same bytes.

## @plantcraft/ui 0.96.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.96.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.96.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
29d7158a78cbfe91db8af9e05980135d967cc8560da8a622f05618fadfbbf037  plantcraft_sdk-0.92.0-py3-none-any.whl
5dc93fe79e20c792777857d40706d196477ed20effbdb6af9c6552a9d00ff425  plantcraft-ui-0.96.0.tgz
```
