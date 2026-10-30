# vendor

Two packages of PlantCraft that are published on no index. StarterCraft pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.79.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.79.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
55c95c0): every app on SDK 0.79.0 vendors these same bytes.

## @plantcraft/ui 0.89.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.89.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.89.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
cf873a199dd6974c4462430b0a54a1fbc9c47bc092c0b64171b839b2a90d9bd4  plantcraft_sdk-0.79.0-py3-none-any.whl
c8d90d75212d5dbdbf37c996e4245e3a62dd4b14a8fdbe72b223f87d61e7454d  plantcraft-ui-0.89.0.tgz
```
