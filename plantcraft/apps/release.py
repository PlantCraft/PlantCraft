"""Releases of the suite: ``release.json``, release notes and the bundle's signature.

``deploy/bundle.sh`` writes them (``make``, ``sign``) and ``install.sh`` checks a bundle with
the installer image of the version already installed (``check``) before it changes anything, so
the trust comes from what runs, never from the bundle that asks to replace it
(docs/operations.md, section 3)::

    release.json      suite version, upgrade_from, each module's version, every image and its id,
                      each app's [permissions] from the app.toml inside its image
    RELEASE-NOTES.md  the CHANGELOG.md entry of each module for its version
    SHA256SUMS        hash of every file of the bundle (both above included)
    SHA256SUMS.sig    Ed25519 signature over SHA256SUMS by a trusted publisher (JSON)

Beside the bundle's archive, ``<archive>.sha256.sig`` signs the archive's hash with the same key in
OpenSSH's signature format (``sign-file``), so that an administrator checks the download with
``ssh-keygen -Y verify`` before unpacking anything, with no tool of ours (docs/install-offline.md).
``fingerprint`` prints what the publisher publishes for that: the key id, the OpenSSH fingerprint
and the ``allowed_signers`` line.

``make`` and ``check`` need only the standard library; ``sign``, ``sign-file``, ``fingerprint``
and a signature check need ``cryptography`` (``plantcraft.apps.package``), which the installer
image carries.

The permissions of the suite's apps are pinned there (security audit, 2026-10-26): PlantCraft
holds each app's token to the list its signed release names (``plantcraft.apps.scopes``), so an
app of the suite cannot grant itself more by changing what it declares when it starts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import struct
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORMAT = 1
RELEASE = "release.json"
NOTES = "RELEASE-NOTES.md"
SUMS = "SHA256SUMS"
SIGNATURE = "SHA256SUMS.sig"
# OpenSSH signatures (PROTOCOL.sshsig): the namespace ssh-keygen uses for files.
SSH_NAMESPACE = "file"
# The name ssh-keygen prints; a label only (a signature does not carry it), so it is the product's
# name while the publisher id and its key files keep the old one.
SSH_IDENTITY = "release@plantcraft"
ARCHITECTURES = ("amd64", "arm64")
VERSION = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,6})(?:-([0-9A-Za-z.-]{1,40}))?$")
COMPONENT = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
NAMES = {
    "processcraft": "PlantCraft",
    "linkcraft": "PlantCraft Analytics",
    "dashcraft": "PlantCraft View",
    "histcraft": "PlantCraft Historian",
    "alarmcraft": "PlantCraft Alarms",
    "modelcraft": "PlantCraft Models",
    "doccraft": "PlantCraft Documents",
    "simcraft": "PlantCraft Simulator",
}


class ReleaseError(ValueError):
    """The bundle is refused; ``str(error)`` says why, for the administrator."""


def version_key(version: str) -> tuple[int, int, int, int, str]:
    """Order of SemVer versions: ``0.2.0-rc.1`` < ``0.2.0`` < ``0.10.0``."""

    match = VERSION.match(version or "")
    if not match:
        raise ReleaseError(f"not a version: {version!r}")
    major, minor, patch, pre = match.groups()
    return int(major), int(minor), int(patch), 0 if pre else 1, pre or ""


def changelog_entry(text: str, version: str) -> str | None:
    """The body of ``## [<version>]`` in a Keep a Changelog file, or None."""

    heading = re.compile(rf"^## \[{re.escape(version)}\](?:\s|$)")
    lines, found = [], False
    for line in text.splitlines():
        if found and line.startswith("## "):
            break
        if found:
            lines.append(line)
        elif heading.match(line):
            found = True
    return "\n".join(lines).strip() if found else None


def bundle_env(path: Path) -> dict[str, Any]:
    """``bundle.env``: its values, and the image ids of its ``# <ref> <id>`` lines."""

    values: dict[str, str] = {}
    images: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            parts = line[2:].split()
            if len(parts) == 2 and parts[1].startswith("sha256:"):
                images.append({"ref": parts[0], "id": parts[1]})
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip():
            values[key.strip()] = value.strip()
    return {"values": renamed_settings(values), "images": images}


FORMER_PREFIX = "PROCESS" + "CRAFT_"  # the settings' prefix before PlantCraft (2026-10-27)


def renamed_settings(values: dict[str, str]) -> dict[str, str]:
    """A bundle.env written before the rename to PlantCraft, in today's names: there
    ``PLANTCRAFT_VERSION`` is the Simulator's (``SIMCRAFT_VERSION`` now) and the platform's
    settings start with the former prefix."""

    if not any(key.startswith(FORMER_PREFIX) for key in values):
        return values
    renamed = {key: value for key, value in values.items() if key != "PLANTCRAFT_VERSION"}
    if "PLANTCRAFT_VERSION" in values:
        renamed.setdefault("SIMCRAFT_VERSION", values["PLANTCRAFT_VERSION"])
    for key, value in values.items():
        if key.startswith(FORMER_PREFIX):
            del renamed[key]
            renamed["PLANTCRAFT_" + key[len(FORMER_PREFIX) :]] = value
    return renamed


def manifest_permissions(path: str | Path) -> list[str]:
    """``read.<name>`` and ``write.<name>`` of an ``app.toml``'s ``[permissions]``, sorted."""

    with Path(path).open("rb") as handle:
        document = tomllib.load(handle)
    section = document.get("permissions") or {}
    if not isinstance(section, dict):
        raise ReleaseError(f"{path}: [permissions] is not a table")
    found: set[str] = set()
    for kind in ("read", "write"):
        names = section.get(kind) or []
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ReleaseError(f"{path}: [permissions] {kind} is not a list of names")
        found.update(f"{kind}.{name}" for name in names)
    return sorted(found)


# Settings prefix -> component id, where the two differ.
COMPONENT_IDS = {"plantcraft": "processcraft"}


def make(
    bundle: str | Path,
    *,
    upgrade_from: str,
    changelogs: dict[str, Path],
    manifests: dict[str, Path] | None = None,
    created: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Write ``release.json`` and ``RELEASE-NOTES.md``; returns the release and the warnings."""

    folder = Path(bundle)
    env = bundle_env(folder / "bundle.env")
    values = env["values"]
    version = values.get("PLANTCRAFT_VERSION", "")
    version_key(version)
    version_key(upgrade_from)
    if version_key(upgrade_from) > version_key(version):
        raise ReleaseError(f"upgrade_from {upgrade_from} is above the version {version}")
    components: dict[str, dict[str, Any]] = {}
    for key, value in sorted(values.items()):
        if not key.endswith("_VERSION") or not value:
            continue
        component = key[: -len("_VERSION")].lower()
        # The platform's id stays processcraft; the Simulator's is simcraft (2026-10-27).
        component = COMPONENT_IDS.get(component, component)
        version_key(value)
        components[component] = {"name": NAMES.get(component, component), "version": value}
    warnings: list[str] = []
    sections = []
    for component, entry in components.items():
        notes = None
        source = changelogs.get(component)
        if source and source.is_file():
            notes = changelog_entry(source.read_text(encoding="utf-8"), entry["version"])
        if notes is None:
            warnings.append(f"{component} {entry['version']}: no CHANGELOG.md entry for it")
        entry["notes"] = notes is not None
        sections.append(
            f"## {entry['name']} {entry['version']}\n\n{notes or '_No notes for this version._'}\n"
        )
    release = {
        "format": FORMAT,
        "suite": "processcraft",
        "version": version,
        "upgrade_from": upgrade_from,
        "created": created or values.get("CREATED") or _now(),
        "revision": values.get("REVISION", "unknown"),
        "components": components,
        "images": env["images"],
    }
    permissions = {}
    for app, path in sorted((manifests or {}).items()):
        if not COMPONENT.match(app):
            raise ReleaseError(f"invalid app id {app!r}")
        permissions[app] = manifest_permissions(path)
    if permissions:
        release["permissions"] = permissions
    if values.get("ARCH"):
        if values["ARCH"] not in ARCHITECTURES:
            raise ReleaseError(f"bundle.env: unknown architecture {values['ARCH']!r}")
        release["architecture"] = values["ARCH"]
    (folder / RELEASE).write_text(json.dumps(release, indent=2, sort_keys=True) + "\n")
    head = (
        f"# PlantCraft {version}\n\n"
        f"Released {release['created'][:10]}. Updates an installation of {upgrade_from} or later "
        f"(`./install.sh` from this folder: it backs up first and returns by itself when the new "
        f"version does not come up healthy).\n\n"
    )
    (folder / NOTES).write_text(head + "\n".join(sections))
    return release, warnings


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sign(bundle: str | Path, key_path: str | Path, publisher: str) -> dict[str, Any]:
    """``SHA256SUMS.sig``: the publisher's Ed25519 signature over the exact bytes of SHA256SUMS."""

    from plantcraft.apps import package

    folder = Path(bundle)
    if not package.PUBLISHER_ID.match(publisher):
        raise ReleaseError(f"invalid publisher id {publisher!r}")
    key = package.load_private_key(key_path)
    sums = (folder / SUMS).read_bytes()
    document = {
        "format": FORMAT,
        "publisher": publisher,
        "key_id": package.key_id(key.public_key()),
        "signed": SUMS,
        "signature": package.sign(sums, key).decode().strip(),
    }
    (folder / SIGNATURE).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def _ssh_string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def _ssh_public_blob(public: Any) -> bytes:
    from cryptography.hazmat.primitives import serialization

    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _ssh_string(b"ssh-ed25519") + _ssh_string(raw)


def ssh_fingerprint(public: Any) -> str:
    """The key's fingerprint as ``ssh-keygen -l`` prints it (``SHA256:...``)."""

    digest = hashlib.sha256(_ssh_public_blob(public)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def allowed_signers(public: Any, publisher: str) -> str:
    """The ``allowed_signers`` line that lets ``ssh-keygen -Y verify`` check this publisher."""

    from cryptography.hazmat.primitives import serialization

    key = public.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    identity = SSH_IDENTITY
    return f'{identity} namespaces="{SSH_NAMESPACE}" {key.decode()}'


def ssh_signature(data: bytes, key: Any, namespace: str = SSH_NAMESPACE) -> str:
    """``data`` signed in OpenSSH's format (PROTOCOL.sshsig), as ``ssh-keygen -Y sign`` writes."""

    magic, hash_name = b"SSHSIG", b"sha512"
    signed = (
        magic
        + _ssh_string(namespace.encode())
        + _ssh_string(b"")
        + _ssh_string(hash_name)
        + _ssh_string(hashlib.sha512(data).digest())
    )
    signature = _ssh_string(b"ssh-ed25519") + _ssh_string(key.sign(signed))
    blob = (
        magic
        + struct.pack(">I", 1)
        + _ssh_string(_ssh_public_blob(key.public_key()))
        + _ssh_string(namespace.encode())
        + _ssh_string(b"")
        + _ssh_string(hash_name)
        + _ssh_string(signature)
    )
    text = base64.b64encode(blob).decode()
    lines = [text[i : i + 70] for i in range(0, len(text), 70)]
    return "-----BEGIN SSH SIGNATURE-----\n" + "\n".join(lines) + "\n-----END SSH SIGNATURE-----\n"


def sign_file(path: str | Path, key_path: str | Path) -> Path:
    """``<path>.sig``: ``path`` signed for ``ssh-keygen -Y verify -n file`` (the archive's hash)."""

    from plantcraft.apps import package

    source = Path(path)
    key = package.load_private_key(key_path)
    target = source.with_name(source.name + ".sig")
    target.write_text(ssh_signature(source.read_bytes(), key))
    return target


def fingerprint(public_path: str | Path, publisher: str) -> dict[str, str]:
    """What a publisher publishes so that administrators can check its bundles."""

    from plantcraft.apps import package

    public = package.load_public_key(Path(public_path).read_bytes()[:4096])
    return {
        "publisher": publisher,
        "key_id": package.key_id(public),
        "ssh_fingerprint": ssh_fingerprint(public),
        "allowed_signers": allowed_signers(public, publisher),
    }


def read_release(folder: Path) -> dict[str, Any]:
    try:
        release = json.loads((folder / RELEASE).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseError(f"{RELEASE} is missing: this bundle has no release information") from exc
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"{RELEASE} cannot be read: {exc}") from exc
    if not isinstance(release, dict) or release.get("format") != FORMAT:
        raise ReleaseError(f"{RELEASE} is not of a format this version reads")
    version_key(str(release.get("version")))
    version_key(str(release.get("upgrade_from")))
    for component, entry in (release.get("components") or {}).items():
        if not COMPONENT.match(component) or not isinstance(entry, dict):
            raise ReleaseError(f"{RELEASE}: invalid component {component!r}")
        version_key(str(entry.get("version")))
    return release


def _listed(sums: bytes) -> dict[str, str]:
    listed = {}
    for line in sums.decode("utf-8", "replace").splitlines():
        digest, _, name = line.partition("  ")
        if len(digest) == 64 and name:
            listed[name.removeprefix("./")] = digest
    return listed


def check(
    bundle: str | Path,
    *,
    installed: str | None,
    trusted: str | Path | None,
    allow_unsigned: bool = False,
) -> dict[str, Any]:
    """Whether this bundle may replace ``installed``: its release, its signature, its versions.

    The files themselves are checked against SHA256SUMS by ``install.sh`` (``sha256sum -c``);
    here the release files are checked again so that the signature covers what is read.
    """

    folder = Path(bundle)
    problems: list[str] = []
    notes: list[str] = []
    signed_by = None
    try:
        release = read_release(folder)
    except ReleaseError as exc:
        return {"state": "refused", "problems": [str(exc)], "notes": [], "signed_by": None}
    try:
        sums = (folder / SUMS).read_bytes()
    except OSError:
        sums = b""
        problems.append(f"{SUMS} is missing: this is not a complete release bundle")
    listed = _listed(sums)
    for name in (RELEASE, NOTES):
        if name not in listed:
            problems.append(f"{name} is not listed in {SUMS}")
        elif not (folder / name).is_file() or _sha256(folder / name) != listed[name]:
            problems.append(f"{name} does not match {SUMS}: the bundle was modified")
    keys = _trusted(trusted)
    signature = folder / SIGNATURE
    if signature.is_file():
        try:
            signed_by = _verify(sums, signature, keys)
        except ReleaseError as exc:
            problems.append(str(exc))
    elif keys and not allow_unsigned:
        problems.append(
            f"the bundle is not signed ({SIGNATURE} is missing) and this server trusts publisher "
            "keys: get the signed bundle, or pass --allow-unsigned for a development bundle"
        )
    elif keys:
        notes.append("not signed: accepted because of --allow-unsigned")
    else:
        notes.append(
            "no trusted publisher key on this server yet: the signature was not checked "
            "(compare the bundle's SHA-256 with the published one)"
        )
    version = release["version"]
    if installed:
        try:
            if version_key(version) < version_key(installed):
                problems.append(
                    f"this bundle ({version}) is older than the installed version ({installed}): "
                    "going back is a rollback (install.sh --rollback) or a restore "
                    "(install.sh --restore NAME)"
                )
            elif version_key(installed) < version_key(release["upgrade_from"]):
                problems.append(
                    f"{version} updates {release['upgrade_from']} or later; {installed} is "
                    f"installed: update to {release['upgrade_from']} first"
                )
        except ReleaseError as exc:
            problems.append(str(exc))
    return {
        "state": "refused" if problems else "ok",
        "problems": problems,
        "notes": notes,
        "signed_by": signed_by,
        "key_id": package_key_id(keys.get(signed_by)) if signed_by else None,
        "version": version,
        "architecture": release.get("architecture"),
        "upgrade_from": release["upgrade_from"],
        "components": {k: v.get("version") for k, v in release["components"].items()},
    }


def package_key_id(public: Any) -> str:
    from plantcraft.apps import package

    return package.key_id(public)


def _trusted(directory: str | Path | None) -> dict[str, Any]:
    if not directory or not Path(directory).is_dir() or not any(Path(directory).glob("*.pub")):
        return {}
    from plantcraft.apps import package

    return package.load_trusted(directory)


def _verify(sums: bytes, path: Path, keys: dict[str, Any]) -> str:
    from plantcraft.apps import package

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        publisher = str(document["publisher"])
        raw = str(document["signature"]).encode()
        base64.b64decode(raw, validate=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReleaseError(f"{SIGNATURE} cannot be read: {exc}") from exc
    key = keys.get(publisher)
    if key is None:
        raise ReleaseError(
            f"the bundle is signed by {publisher!r}, which this server does not trust "
            "(trusted-publishers/)"
        )
    try:
        package.verify_signature(sums, raw, key)
    except package.PackageError as exc:
        raise ReleaseError(f"{SIGNATURE}: {exc}") from exc
    return publisher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m plantcraft.apps.release")
    commands = parser.add_subparsers(dest="command", required=True)
    made = commands.add_parser("make", help="write release.json and RELEASE-NOTES.md")
    made.add_argument("bundle")
    made.add_argument("--upgrade-from", required=True)
    made.add_argument("--changelog", action="append", default=[], metavar="ID=PATH")
    made.add_argument(
        "--manifest", action="append", default=[], metavar="ID=PATH", help="an app's app.toml"
    )
    signed = commands.add_parser("sign", help="sign SHA256SUMS (SHA256SUMS.sig)")
    signed.add_argument("bundle")
    signed.add_argument("--key", required=True, help="publisher private key (PEM), never shipped")
    signed.add_argument("--publisher", required=True)
    signed_file = commands.add_parser(
        "sign-file", help="sign a file for ssh-keygen -Y verify (<file>.sig)"
    )
    signed_file.add_argument("file")
    signed_file.add_argument(
        "--key", required=True, help="publisher private key (PEM), never shipped"
    )
    printed = commands.add_parser(
        "fingerprint", help="key id, OpenSSH fingerprint, allowed_signers"
    )
    printed.add_argument("public_key")
    printed.add_argument("--publisher", required=True)
    checked = commands.add_parser("check", help="may this bundle replace the installed version")
    checked.add_argument("bundle")
    checked.add_argument("--installed", default="")
    checked.add_argument("--trusted", default="")
    checked.add_argument("--allow-unsigned", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "make":
            changelogs = {}
            for item in args.changelog:
                component, _, path = item.partition("=")
                changelogs[component] = Path(path)
            manifests = {}
            for item in args.manifest:
                app, _, path = item.partition("=")
                manifests[app] = Path(path)
            release, warnings = make(
                args.bundle,
                upgrade_from=args.upgrade_from,
                changelogs=changelogs,
                manifests=manifests,
            )
            for warning in warnings:
                print(f"WARNING: {warning}", file=sys.stderr)
            print(f"{RELEASE}: PlantCraft {release['version']} "
                  f"(from {release['upgrade_from']}), {len(release['components'])} modules")  # fmt: skip
        elif args.command == "sign":
            document = sign(args.bundle, args.key, args.publisher)
            print(f"{SIGNATURE}: signed by {document['publisher']} (key {document['key_id']})")
        elif args.command == "sign-file":
            print(f"{sign_file(args.file, args.key).name}: signed (ssh-keygen -Y verify -n file)")
        elif args.command == "fingerprint":
            for name, value in fingerprint(args.public_key, args.publisher).items():
                print(f"{name}: {value}")
        else:
            outcome = check(
                args.bundle,
                installed=args.installed or None,
                trusted=args.trusted or None,
                allow_unsigned=args.allow_unsigned,
            )
            print(json.dumps(outcome, indent=2, sort_keys=True))
            # What install.sh shows (it keeps standard output for the JSON).
            for problem in outcome["problems"]:
                print(f"refused: {problem}", file=sys.stderr)
            for note in outcome["notes"]:
                print(f"note: {note}", file=sys.stderr)
            if outcome["signed_by"]:
                print(
                    f"signed by {outcome['signed_by']} (key {outcome['key_id']}): "
                    "signature checked",
                    file=sys.stderr,
                )
            return 0 if outcome["state"] == "ok" else 1
    except (ReleaseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # a key error from package.py (PackageError)
        if type(exc).__name__ != "PackageError":
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
