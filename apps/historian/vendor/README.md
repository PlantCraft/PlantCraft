# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Historian pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.104.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.104.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
6600c1d): every app on SDK 0.104.0 vendors these same bytes.

## @plantcraft/ui 0.108.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.108.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.108.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
79432ea83728d73d900e05d28ae340a3b6ce4178b35baf2e81f7599b959e5f23  plantcraft_sdk-0.104.0-py3-none-any.whl
0b8854280e4041c2ebcc10f0b271eeb4f040316b67106afdf56d751e2b1a045b  plantcraft-ui-0.108.0.tgz
```
