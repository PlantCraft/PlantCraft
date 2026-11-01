# vendor

Two packages of PlantCraft that are published on no index. PlantCraft Documents pins both and installs them
only from this folder, so the image builds offline and checks each file's hash. Neither is edited
here: a change is made in `sdk/python` or `ui/` at the repository's root, released as a new
version, and `dev/revendor` puts the new file here with its hash.

## plantcraft-sdk 0.98.0

`pip install --no-index --find-links vendor plantcraft-sdk==0.98.0` (Makefile, CI and the
Dockerfile). The wheel is PlantCraft's reproducible build (`make sdk-wheel`, PlantCraft
26f19a8): every app on SDK 0.98.0 vendors these same bytes.

## @plantcraft/ui 0.102.0

The suite's frame and shared interface parts (PlantCraft `docs/app-standard.md`, section 10).
`frontend/package.json` names it as `"@plantcraft/ui": "file:../vendor/plantcraft-ui-0.102.0.tgz"`;
`npm ci` checks it against the integrity hash in `frontend/package-lock.json`. Built by
PlantCraft's `make ui-package` (every app on ui 0.102.0 vendors the same bytes).

## Checks

The same in `sha256sum -c` format (the Docker build and `plantcraft-app check` check both):

```text
0e8ec2e7730edf20eeeb6726b0de65299fc2211d1ea16167866d98b7c1d1d326  plantcraft_sdk-0.98.0-py3-none-any.whl
5462713f0cee5f0e6006f3220d1e8183dabac95d56b1919f03ce4afe4e26c36d  plantcraft-ui-0.102.0.tgz
```
