# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Documents pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.92.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.92.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
9148e8e): every app on SDK 0.92.0 vendors these same bytes.

## @plantcraft/ui 0.95.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.95.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.95.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
29d7158a78cbfe91db8af9e05980135d967cc8560da8a622f05618fadfbbf037  plantcraft_sdk-0.92.0-py3-none-any.whl
49af598b2ad98e10f73b52ae3faeb402b88f43558d4060b6612bb492bb3e1612  plantcraft-ui-0.95.0.tgz
```
