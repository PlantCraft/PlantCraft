# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Alarms pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.81.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.81.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
25c8fa9): every app on SDK 0.81.0 vendors these same bytes.

## @plantcraft/ui 0.89.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.89.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.89.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
51fa08936b96bf0d8fba819205356194e00eb6b76730d55c65d073b6a83bd335  plantcraft_sdk-0.81.0-py3-none-any.whl
ff182a69145bab8a3665ba148b36fa9c68ba207079500eabbee1fce43a3963af  plantcraft-ui-0.89.0.tgz
```
