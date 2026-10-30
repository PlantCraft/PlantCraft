# Check a release before you install it

For whoever brings a PlantCraft release into a plant. Every release is signed by its publisher,
so you can prove that the bundle you copied is the one the publisher made and that nobody
tampered with it on the way: on the download page, on a USB stick, on a file share. The check
takes about a minute, needs nothing but OpenSSH, and works without internet access.

## What is signed

Each release has, per processor (`linux-amd64` for x86_64, `linux-arm64` for 64-bit ARM):

| File | What it is |
|---|---|
| `plantcraft-<version>-linux-<arch>-bundle.tar.gz` | The bundle: container images, `compose.yaml`, `install.sh`, SBOMs, documentation |
| `....tar.gz.sha256` | The SHA-256 hash of the bundle |
| `....tar.gz.sha256.sig` | The publisher's Ed25519 signature over that hash |

Inside the bundle, `SHA256SUMS` holds the hash of every file (the images included) and
`SHA256SUMS.sig` the publisher's signature over it. So the release is checked twice: by you,
before you unpack it, and by `install.sh`, before it changes anything.

## The publisher's key

The publisher **PlantCraft** signs every release with one Ed25519 key. Compare what you use with
at least two of these places: this page, the release page, and
`deploy/trusted-publishers/` in the repository.

| | |
|---|---|
| Key id (what `install.sh` prints) | `af2643fa16867976` |
| OpenSSH fingerprint (`ssh-keygen -l`) | `SHA256:9l/yDgR8/Pzel1pncxrXz2IGCIhFirKpDT78tO49fG8` |
| The line for `ssh-keygen` | `release@plantcraft namespaces="file" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMwhizmfd8aZQ1zHpVLpIrrgxv/YlT/ufewCBueO0hnE` |

Keep a copy of the key apart from the bundles you receive (for example on the plant's admin
workstation): a bundle carries its own copy of the key, and a key that travels with the file it
vouches for proves less than one you already hold.

## Check the bundle (Linux and macOS)

With OpenSSH 8.1 or later, which every supported Linux and macOS already has, in the folder that
holds the three files. The first line writes the publisher's key: compare it with the table above
before you go on.

```bash
echo 'release@plantcraft namespaces="file" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMwhizmfd8aZQ1zHpVLpIrrgxv/YlT/ufewCBueO0hnE' \
    > plantcraft.allowed_signers
B=plantcraft-0.5.0-linux-amd64-bundle.tar.gz
ssh-keygen -Y verify -f plantcraft.allowed_signers -I release@plantcraft -n file \
    -s $B.sha256.sig < $B.sha256      # Good "file" signature for release@plantcraft ...
sha256sum -c $B.sha256               # plantcraft-...tar.gz: OK   (macOS: shasum -a 256 -c $B.sha256)
```

Both lines must say so: `Good "file" signature for release@plantcraft` from the first, `OK`
from the second. Only then unpack the bundle and install it ([install.md](install.md)).

## Check the bundle on Windows

On Windows the suite installs from Ubuntu in WSL ([install.md](install.md), Windows). Copy the
three files into your Linux home folder as that section says, and run the same commands as above
in the Ubuntu window: Ubuntu has OpenSSH and `sha256sum`.

## What the installer checks again

`install.sh` checks the release from the inside before it changes anything:

- every file against `SHA256SUMS`, and `SHA256SUMS.sig` against the publisher keys. A first
  install trusts the key the bundle carries, or, with `--publisher-key processcraft.pub`, your own
  copy of it; from then on the installation trusts only the keys in its `trusted-publishers/`
  folder;
- on an update, the signature is checked by the installer already installed, never by the new
  one, against the installation's `trusted-publishers/`. A bundle that is not signed by a trusted
  publisher, or that is older than what runs, is refused with nothing changed
  ([install-offline.md](install-offline.md), section 7);
- an app package (`.pcapp`) added later is checked the same way: Ed25519 signature of its
  manifest, SHA-256 of its image and of its SBOM, and its publisher must be in
  `trusted-publishers/` ([app-package.md](app-package.md)).

A development bundle that nobody signed installs only with `--allow-unsigned`; never use one at
a plant.

## What the signature proves, and what it does not

- **It proves** that the bundle is byte for byte the one the holder of the publisher's key
  signed: no file was changed, added or removed after signing.
- **It does not prove** that the software has no flaw. For that the release carries CycloneDX
  software bills of materials (`sbom/` in the bundle), CI checks every change with `pip-audit` and
  `npm audit`, and base images are pinned by digest
  ([security-guide.md](security-guide.md), section 7).

## If a check fails

Do not unpack or install the bundle. Copy the three files again from the release page and check
once more; if it still fails, delete them and tell the publisher privately, as a vulnerability
report ([SECURITY.md](../SECURITY.md)).
