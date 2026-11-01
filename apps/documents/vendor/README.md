# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Documents pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.101.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.101.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
143c87b): every app on SDK 0.101.0 vendors these same bytes.

## @plantcraft/ui 0.105.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.105.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.105.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
e56b052fc905e52f3434954df8c300d60a60a6e5a312b95acfd429d6f6139714  plantcraft_sdk-0.101.0-py3-none-any.whl
a36410ce8272c14764d95717e261e803649867305d82c4f4223f4db84ab836e9  plantcraft-ui-0.105.0.tgz
```
