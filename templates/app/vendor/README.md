# vendor

Two packages of PlantCraft that are published on no index. StarterCraft pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.107.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.107.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
93947c2): every app on SDK 0.107.0 vendors these same bytes.

## @plantcraft/ui 0.114.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.114.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.114.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
f36d7b991131fdf42a5bf05b2692d9d658b5a7bfd5ae57be5e946a814126da52  plantcraft_sdk-0.107.0-py3-none-any.whl
62617f867de93479c7bace62e8c717540e1107bdde60b3cbce1634c98a241cf3  plantcraft-ui-0.114.0.tgz
```
