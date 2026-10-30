# 05: Package and install

```text
Build the app's image and signed package and install it on a PlantCraft stack.

For a development stack:
1. In the PlantCraft checkout, once: `make dev-publisher` (a development key that a development
   stack trusts; never shipped).
2. In this folder: `make dev-package`. It builds the image <app>:<version> and
   dist/<app>-<version>.pcapp. app.toml's publisher must be "Dev Publisher" for this key.
3. On the stack: PlantCraft > Apps > Install from file, pick the .pcapp, check the permissions
   shown, install, give the app access to a person under Users, open it from the launcher.

For a real stack: make a publisher key pair once
(`python3 plantcraft/apps/package.py keygen --name "<Company>" --out-dir <safe folder>` in
PlantCraft), keep the .key outside every repository, set app.toml's publisher to "<Company>",
give the stack's admin the .pub for deploy/trusted-publishers/, then
`make package PUBLISHER_KEY=<safe folder>/<company>.key`.
```
