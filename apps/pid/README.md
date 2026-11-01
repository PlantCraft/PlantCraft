<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="PlantCraft PID"></p>

# PlantCraft PID

The plant's P&IDs read into a plant map: units, equipment, lines and control loops. Send P&IDs as
PDF, SVG, DEXPI (XML) or scans; PID reads the tags, the equipment and instruments they name and the
lines and signals that join them, offline and with no language model, and joins the sheets into
one map that an engineer checks and exports (asset file, DEXPI, lists, a Markdown summary).

PID is the suite's first **closed app** (docs/app-package.md, section 8):

- its image carries the app compiled with Nuitka into one native module (no `.py`, no `.pyc`;
  the Dockerfile fails if any is left) and the interface minified with no source maps;
- `app.toml` says `source = "closed"`, a `LicenseRef` licence and `[license] required = true`;
- it works only with a `.pclicense` signed by its publisher for the installation
  (`src/pidcraft/licence.py`, `plantcraft_sdk.licensing`), checked at start and every hour, with
  14 days of grace after the end day and the `sheets` limit on the number of drawings.

The source in this folder is the publisher's; a client receives the package only.

## Develop

```sh
make ci          # app standard, lint, interface build and tests, pytest (from source)
make dev         # the Simulator, PlantCraft on :8060 and PID on :8160
make image       # the closed image: compiles with Nuitka, checks no source is left
make package PUBLISHER_KEY=...   # the signed .pcapp
```

A licence for a development installation:

```sh
plantcraft-app license issue --key keys/dev-publisher.key --app pidcraft --publisher PlantCraft \
    --customer "Development" --installation '*' --expires 2027-12-31 --out dev.pclicense
```

and add `dev.pclicense` in PlantCraft's Apps › Licences.

See [SPEC.md](SPEC.md) for what it does and its sources, and [docs/help/pidcraft.md](docs/help/pidcraft.md)
for the help page.
