# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Models pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.83.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.83.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
45f59f3): every app on SDK 0.83.0 vendors these same bytes.

## @plantcraft/ui 0.90.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.90.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.90.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
9bf6b395826d13150435374b34ab03af0b263b7c12265462e74c90b7ccd5f9a1  plantcraft_sdk-0.83.0-py3-none-any.whl
66fed2821b0b258c0d5efa991a389b0fcea06c4b139ad5a2260fd3e594bfa929  plantcraft-ui-0.90.0.tgz
```
