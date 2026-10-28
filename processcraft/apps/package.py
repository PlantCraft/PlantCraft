"""Signed app packages: build, sign and verify (docs/app-package.md, docs/app-standard.md).

One file, standard library plus ``cryptography``, importing nothing else from
PlantCraft: the installer image runs it, ``install.sh --add`` runs it through
that image, and another repository (LinkCraft) can run it as a script to build
and sign its own package::

    python package.py keygen --name my-publisher --out-dir keys/
    python package.py build --manifest app.toml --image-tar image.tar \\
        --sbom sbom.spdx.json --key keys/my-publisher.key --out myapp-0.1.0.pcapp
    python package.py verify --trusted deploy/trusted-publishers myapp-0.1.0.pcapp

A package is a tar (optionally gzip-compressed) holding exactly four regular
files: ``manifest.json``, ``manifest.sig`` (Ed25519 over the exact bytes of
``manifest.json``, base64), ``image.tar`` (``docker save`` of one image) and
``sbom.spdx.json``. The manifest is the app's ``app.toml`` as JSON (sections
``app``, ``runtime``, ``requires``, ``permissions``, ``publishes``, ``consumes``,
``suggests``) plus ``files``: the SHA-256 and size of the other two.
Verification reads the tar as a stream, never extracts anything by name from
the archive and never follows links: a member that is not one of those four
regular files rejects the whole package.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


FORMAT = 1
MANIFEST, SIGNATURE, IMAGE, SBOM = "manifest.json", "manifest.sig", "image.tar", "sbom.spdx.json"
MEMBERS = (MANIFEST, SIGNATURE, SBOM, IMAGE)
PAYLOAD = (IMAGE, SBOM)
KiB, MiB, GiB = 1024, 1024**2, 1024**3
DEFAULT_MAX_IMAGE_BYTES = 4 * GiB
LIMITS = {MANIFEST: 64 * KiB, SIGNATURE: 1 * KiB, SBOM: 16 * MiB}
# Small members of image.tar that say which image it holds; the layers are only hashed.
IMAGE_META = {"manifest.json", "index.json", "repositories"}
IMAGE_META_LIMIT = 1 * MiB
IMAGE_MAX_MEMBERS = 20_000
CHUNK = 1 * MiB
INDEX_LIMIT = 1 * MiB

APP_ID = re.compile(r"^[a-z][a-z0-9]{2,30}$")
PUBLISHER_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
PUBLISHER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .&_-]{1,59}$")
VERSION = re.compile(r"^[0-9]{1,6}(\.[0-9]{1,6}){1,3}(-[0-9A-Za-z.]{1,40})?$")
PREFIX = re.compile(r"^/[a-z][a-z0-9-]{0,30}/$")
HEALTH = re.compile(r"^/[A-Za-z0-9/_.-]{0,100}$")
WORD = re.compile(r"^[a-z][a-z0-9_.:-]{0,60}$")
RANGE = re.compile(r"^[<>=!~^ .,0-9*]{1,40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# The suite table of docs/app-standard.md (section 7): id -> (prefix, port, uid). An app listed
# here must use exactly its row; any other app may use none of these values.
# CPMCraft's, DataCraft's and PlantCraft Twin's rows are retired (all merged into LinkCraft)
# and stay reserved: no new app takes their prefix, port or container user.
SUITE = {
    "cpmcraft": ("/cpm/", 8070, 10002),
    "dashcraft": ("/dash/", 8080, 10006),
    "datacraft": ("/quality/", 8090, 10007),
    "histcraft": ("/hist/", 8100, 10008),
    "alarmcraft": ("/alarm/", 8110, 10009),
    "twincraft": ("/twin/", 8120, 10010),
    "modelcraft": ("/model/", 8130, 10011),
    "linkcraft": ("/link/", 8140, 10012),
    "doccraft": ("/doc/", 8150, 10015),
}
# The rest of the table: the services of the stack itself (PlantCraft, proxy, the Simulator, installer).
STACK_PORTS = {8060, 8443, 4840, 3128}
STACK_UIDS = {10001, 10003, 10004, 10005, 10014}
FIRST_UID, LAST_UID = 10002, 65533
# An app outside the table may name no port and no uid (scale review E5; the SDK's app_manifest
# keeps the same rule): every app listens on DEFAULT_PORT in its own container, its user comes
# from its id. Only its prefix must be its own on an installation.
DEFAULT_PORT = 8000
FIRST_OWN_UID, OWN_UIDS = 20000, 40000


def default_uid(app_id: str) -> int:
    """The container user of an app that names none: from its id, in 20000-59999."""

    return FIRST_OWN_UID + int(hashlib.sha256(app_id.encode()).hexdigest()[:8], 16) % OWN_UIDS


# Ids and first path segments that belong to PlantCraft itself (its services, its pages and
# its API); an app may not take them.
RESERVED_IDS = {"processcraft", "proxy", "installer", "plantcraft", "simcraft", "api", "app", "apps"}
RESERVED_SEGMENTS = {
    "api", "assets", "apps", "login", "logout", "plant", "data", "settings", "help", "healthz",
    "docs", "static", "favicon.ico", "robots.txt", "index.html",
}  # fmt: skip
APP_KEY = re.compile(r"^pck_[0-9a-f]{12}\.[A-Za-z0-9_-]{20,100}$")
REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")

# [permissions] of app.toml: what an app may ask for; anything else rejects the package. Shown to
# the administrator before the install (wording for people is translated in the UI), and held
# to every API v1 route afterwards. The same lists as plantcraft_sdk.scopes (the installer
# imports no SDK; tests/test_app_scopes.py holds the two equal).
READ_SCOPES = {
    "assets": "Read the assets and their tree",
    "signals": "Read the signals and their metadata",
    "series": "Read signal values (time series)",
    "results": "Read results published by apps",
    "events": "Read events published by apps",
    "runs": "Read the runs apps record",
    "schedules": "Read the schedules apps keep",
    "people": "Read the people and groups (names only)",
    "knowledge": "Read the knowledge apps keep for the assistant",
}
WRITE_SCOPES = {
    "audit": "Write entries to the audit log",
    "results": "Publish its own results",
    "events": "Publish its own events",
    "runs": "Record its own runs",
    "schedules": "Keep its own schedules",
    "series": "Write its own derived series",
    "notifications": "Send notifications to people",
    "knowledge": "Keep knowledge for the assistant",
    "compute": "Send computations to the suite's compute workers",
    "llm": "Send text to a language model an administrator set up",
}
PERMISSIONS = {
    **{f"read.{name}": label for name, label in READ_SCOPES.items()},
    **{f"write.{name}": label for name, label in WRITE_SCOPES.items()},
}
SECTIONS = {
    "app": {"id", "name", "version", "category", "summary", "description", "publisher",
            "license", "homepage", "mark"},
    "runtime": {"prefix", "port", "uid", "health", "image"},
    "requires": {"processcraft_api", "sdk", "asset_types", "roles"},
    "permissions": {"read", "write", "plant_write", "outbound"},
    "publishes": {"results", "events", "series"},
    "consumes": {"results", "events"},
    "suggests": {"asset_types"},
    "backup": {"sqlite", "files", "skip"},
    # What the app adds to PlantCraft (plantcraft_sdk.contributes checks each table in full in
    # the app's CI and when the app sends it); here the shape, without importing the SDK.
    "contributes": {"llm", "widgets", "search", "calendar", "todo", "refs", "settings", "setup",
                    "queue", "assistant", "objects", "notebooks", "start"},
}  # fmt: skip
# The JSON of [contributes] and [[publishes.series]] together, at most.
CONTRIBUTES_BYTES = 64_000
MANIFEST_FIELDS = {"format", "files", *SECTIONS}


# Publishers renamed after their key went out: the new name -> the key's file name.
FORMER_PUBLISHER_IDS = {"plantcraft": "processcraft"}


def publisher_id(name: str) -> str:
    """The trusted key's file name for a publisher: ``Acme Tools`` -> ``acme-tools.pub``.

    PlantCraft signs with its first key (``processcraft.pub``, in every
    installation's trusted publishers): renamed 2026-10-27, same key.
    """

    found = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return FORMER_PUBLISHER_IDS.get(found, found)


def prefix_owner(app_id: str, prefix: str, taken: dict[str, str]) -> str | None:
    """Who else serves ``prefix`` (``taken`` maps prefixes to app ids), or None when it is free."""

    suite = {row[0]: owner for owner, row in SUITE.items()}
    for owners in (suite, taken):
        owner = owners.get(prefix)
        if owner is not None and owner != app_id:
            return owner
    return None


def runtime_conflict(manifest: dict[str, Any], others: list[dict[str, Any]]) -> str | None:
    """Why ``manifest`` cannot run beside ``others`` (flat views of installed apps), or None."""

    app = flat(manifest)
    for other in others:
        if other.get("id") == app["id"]:
            continue
        # Ports and users are each container's own; two apps may never share an address.
        if other.get("prefix") == app["prefix"]:
            return f"prefix {app['prefix']} is already used by {other.get('id')}"
    return None


class PackageError(ValueError):
    """The package is refused; ``str(error)`` says why, for the administrator."""


# Keys ---------------------------------------------------------------------------------------


def key_id(public: Ed25519PublicKey) -> str:
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def load_public_key(data: bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise PackageError("not an Ed25519 public key")
    return key


def load_private_key(path: str | Path) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise PackageError(f"cannot read the private key {path}: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise PackageError(f"{path} is not an Ed25519 private key")
    return key


def load_trusted(directory: str | Path | None) -> dict[str, Ed25519PublicKey]:
    """``{publisher id: key}`` from ``<publisher id>.pub`` files (PEM); bad files are skipped."""

    keys: dict[str, Ed25519PublicKey] = {}
    if not directory:
        return keys
    folder = Path(directory)
    if not folder.is_dir():
        return keys
    for path in sorted(folder.glob("*.pub")):
        if not PUBLISHER_ID.match(path.stem) or not path.is_file():
            continue
        try:
            keys[path.stem] = load_public_key(path.read_bytes()[: 4 * KiB])
        except (OSError, ValueError, PackageError):
            continue
    return keys


def keygen(name: str, out_dir: str | Path) -> tuple[Path, Path]:
    """A new publisher key pair: ``<name>.key`` (private, mode 0600) and ``<name>.pub``."""

    if not PUBLISHER_ID.match(name):
        raise PackageError("publisher name: 2 to 40 lower-case letters, digits or hyphens")
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    private_path, public_path = folder / f"{name}.key", folder / f"{name}.pub"
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    try:
        descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PackageError(f"{private_path} already exists; refusing to overwrite a key") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(private)
    public_path.write_bytes(public)
    return private_path, public_path


def sign(data: bytes, key: Ed25519PrivateKey) -> bytes:
    return base64.b64encode(key.sign(data)) + b"\n"


def verify_signature(data: bytes, signature: bytes, key: Ed25519PublicKey) -> None:
    try:
        raw = base64.b64decode(signature.strip(), validate=True)
    except (ValueError, TypeError) as exc:
        raise PackageError("the signature is not base64") from exc
    if len(raw) != 64:
        raise PackageError("the signature is not an Ed25519 signature")
    try:
        key.verify(raw, data)
    except InvalidSignature as exc:
        raise PackageError("the signature does not match: the package was modified") from exc


# JSON ---------------------------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PackageError(f"duplicate key {key!r} in JSON")
        result[key] = value
    return result


def strict_json(data: bytes, what: str) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageError(f"{what} is not UTF-8") from exc
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constants)
    except PackageError:
        raise
    except (ValueError, RecursionError) as exc:
        raise PackageError(f"{what} is not valid JSON: {exc}") from exc


def _no_constants(name: str) -> Any:
    raise PackageError(f"{name} is not allowed in JSON")


# Manifest -----------------------------------------------------------------------------------


def _text(value: Any, what: str, limit: int, *, required: bool = True) -> str:
    if value in (None, "") and not required:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PackageError(f"{what}: a text of 1 to {limit} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise PackageError(f"{what}: control characters are not allowed")
    return value.strip()


def _int(value: Any, what: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise PackageError(f"{what}: a whole number from {low} to {high}")
    return value


def _section(manifest: dict[str, Any], name: str, *, required: bool = False) -> dict[str, Any]:
    section = manifest.get(name)
    if section is None and not required:
        return {}
    if not isinstance(section, dict):
        raise PackageError(f"[{name}] is missing or is not a table")
    unknown = sorted(set(section) - SECTIONS[name])
    if unknown:
        raise PackageError(f"[{name}]: unknown keys {unknown}")
    return section


def _words(value: Any, what: str, *, allowed: Any = None, limit: int = 50) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise PackageError(f"{what}: a list of at most {limit} names")
    for item in value:
        if not isinstance(item, str) or not WORD.match(item):
            raise PackageError(f"{what}: {str(item)[:40]!r} is not a valid name")
        if allowed is not None and item not in allowed:
            raise PackageError(
                f"{what}: unknown {item!r}; allowed are {', '.join(sorted(allowed))}"
            )
    if len(set(value)) != len(value):
        raise PackageError(f"{what}: repeated names")
    return list(value)


EVENT_KEYS = {"name", "title", "description", "severity", "category", "phase", "payload", "rule"}


def _event_tables(events: list[Any]) -> list[Any]:
    if len(events) > 100:
        raise PackageError("[publishes] events: a list of at most 100")
    names = []
    for item in events:
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str) or not WORD.match(name):
            raise PackageError("[publishes] events: each has a name like finding.opened")
        if isinstance(item, dict):
            unknown = set(item) - EVENT_KEYS
            if unknown:
                raise PackageError(f"[publishes] events: unknown keys {sorted(unknown)}")
            if not isinstance(item.get("title"), str) or not item["title"].strip():
                raise PackageError(f"[publishes] events: {name} needs a title")
        names.append(name)
    if len(set(names)) != len(names):
        raise PackageError("[publishes] events: repeated names")
    return list(events)


def _tables(value: Any, what: str, limit: int = 50) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > limit:
        raise PackageError(f"{what}: a list of at most {limit} tables")
    if not all(isinstance(item, dict) for item in value):
        raise PackageError(f"{what}: each item is a table")
    return [dict(item) for item in value]


def _contributes(section: dict[str, Any]) -> dict[str, Any]:
    """``[contributes]``: tables of tables, ``search`` and ``notebooks`` tables, ``assistant`` a table of works
    and offers, ``queue`` true or false."""

    clean: dict[str, Any] = {}
    for key, value in section.items():
        if key == "queue":
            if not isinstance(value, bool):
                raise PackageError("[contributes] queue: true or false")
            clean[key] = value
        elif key in ("search", "notebooks"):
            if not isinstance(value, dict):
                raise PackageError(f"[contributes.{key}]: a table")
            clean[key] = dict(value)
        elif key == "assistant":
            # The assistant's works, the PlantCraft works the app offers on its pages and the
            # read-only tools it adds (checked in full when the app sends its contributions).
            if not isinstance(value, dict) or set(value) - {"works", "offers", "tools"}:
                raise PackageError("[contributes.assistant]: a table of works, offers and tools")
            clean[key] = {
                name: _tables(items, f"[contributes.assistant] {name}", 60)
                for name, items in value.items()
            }
        else:
            clean[key] = _tables(value, f"[contributes] {key}")
    return clean


# A path inside the app's data folder ([backup]), as plantcraft_sdk.app_manifest allows it.
DATA_PATH = re.compile(r"^[A-Za-z0-9._-][A-Za-z0-9._/-]{0,199}$")


def _backup(section: dict[str, Any]) -> dict[str, Any]:
    clean = {}
    for key, value in section.items():
        if not isinstance(value, list) or len(value) > 100:
            raise PackageError(f"[backup] {key}: a list of at most 100 paths")
        for item in value:
            if not isinstance(item, str) or not DATA_PATH.match(item) or ".." in item.split("/"):
                raise PackageError(
                    f"[backup] {key}: {str(item)[:40]!r} is not a path inside the data folder"
                )
        clean[key] = list(value)
    return clean


def _links(section: dict[str, Any], name: str) -> dict[str, Any]:
    """``[publishes]`` and ``[consumes]``: results ``{kind, subject}`` and event names."""

    results = section.get("results", [])
    if not isinstance(results, list) or len(results) > 50:
        raise PackageError(f"[{name}] results: a list of at most 50")
    clean = []
    for item in results:
        if not isinstance(item, dict) or set(item) != {"kind", "subject"}:
            raise PackageError(f'[{name}] results: {{ kind = "...", subject = "..." }}')
        for key in ("kind", "subject"):
            if not isinstance(item[key], str) or not WORD.match(item[key]):
                raise PackageError(f"[{name}] results: invalid {key}")
        clean.append({"kind": item["kind"], "subject": item["subject"]})
    out: dict[str, Any] = {"results": clean} if "results" in section else {}
    if "events" in section:
        events = section["events"]
        if (
            name == "publishes"
            and isinstance(events, list)
            and any(isinstance(item, dict) for item in events)
        ):
            # [[publishes.events]] tables (plantcraft_sdk.events checks them in full when the
            # app sends its catalog): here the shape, without importing the SDK.
            out["events"] = _event_tables(events)
        else:
            out["events"] = _words(events, f"[{name}] events")
    if "series" in section:
        out["series"] = _tables(section["series"], f"[{name}] series")
    return out


def validate_manifest(manifest: Any, *, with_files: bool = True) -> dict[str, Any]:
    """The manifest (``app.toml`` plus ``files``), checked key by key; raises PackageError."""

    if not isinstance(manifest, dict):
        raise PackageError("manifest.json must be a JSON object")
    unknown = set(manifest) - MANIFEST_FIELDS
    if unknown:
        raise PackageError(f"manifest.json: unknown sections {sorted(unknown)}")
    if manifest.get("format") != FORMAT:
        raise PackageError(f"manifest.json: format must be {FORMAT}")
    app = _section(manifest, "app", required=True)
    runtime = _section(manifest, "runtime", required=True)
    permissions = _section(manifest, "permissions", required=True)
    app_id = app.get("id")
    if not isinstance(app_id, str) or not APP_ID.match(app_id):
        raise PackageError("[app] id: 3 to 31 lower-case letters or digits, starting with a letter")
    if app_id in RESERVED_IDS:
        raise PackageError(f"id {app_id!r} is reserved for the stack of PlantCraft")
    version = app.get("version")
    if not isinstance(version, str) or not VERSION.match(version):
        raise PackageError("[app] version: numbers separated by dots, like 1.2.0 or 1.2.0-rc.1")
    publisher = app.get("publisher")
    if (
        not isinstance(publisher, str)
        or not PUBLISHER_NAME.match(publisher)
        or not PUBLISHER_ID.match(publisher_id(publisher))
    ):
        raise PackageError("[app] publisher: 2 to 60 letters, digits, spaces, dots or hyphens")
    homepage = _text(app.get("homepage"), "[app] homepage", 200, required=False)
    if homepage and not re.fullmatch(r"https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[^\s]*)?", homepage):
        raise PackageError("[app] homepage: an https:// address")
    mark = app.get("mark", "")
    if mark and (not isinstance(mark, str) or not WORD.match(mark)):
        raise PackageError("[app] mark: a lower-case name")
    prefix = runtime.get("prefix")
    if not isinstance(prefix, str) or not PREFIX.match(prefix):
        raise PackageError("[runtime] prefix: one path segment between slashes, like /cpm/")
    if prefix.strip("/") in RESERVED_SEGMENTS:
        raise PackageError(f"prefix {prefix} belongs to PlantCraft")
    port = _int(runtime.get("port", DEFAULT_PORT), "[runtime] port", 1024, 65535)
    own = SUITE[app_id][2] if app_id in SUITE else default_uid(app_id)
    uid = _int(runtime.get("uid", own), "[runtime] uid", FIRST_UID, LAST_UID)
    health = runtime.get("health", "/healthz")
    if not isinstance(health, str) or not HEALTH.match(health):
        raise PackageError("[runtime] health: a path like /healthz")
    if runtime.get("image") != app_id:
        raise PackageError(
            f'[runtime] image must be "{app_id}" (the app id; the tag is the version)'
        )
    row = SUITE.get(app_id)
    if row is not None and (prefix, port, uid) != row:
        raise PackageError(
            f"{app_id} is in the suite table: prefix {row[0]}, port {row[1]}, uid {row[2]}"
        )
    if row is None:
        # The port is the app's own container's: any. Its prefix and its user are its own.
        for owner, (other_prefix, _port, other_uid) in SUITE.items():
            for value, other, what in ((prefix, other_prefix, "prefix"), (uid, other_uid, "uid")):
                if value == other:
                    raise PackageError(f"{what} {value} belongs to {owner} in the suite table")
        if uid in STACK_UIDS:
            raise PackageError("the uid belongs to the stack of PlantCraft")
    if permissions.get("plant_write", False) is not False:
        raise PackageError("[permissions] plant_write must be false: no app writes to the plant")
    if permissions.get("outbound", []) != []:
        raise PackageError("[permissions] outbound must be []: apps contact no outside host")
    requires = _section(manifest, "requires")
    clean_requires: dict[str, Any] = {}
    for key in ("processcraft_api", "sdk"):
        if key in requires:
            value = requires[key]
            if not isinstance(value, str) or not RANGE.match(value):
                raise PackageError(f"[requires] {key}: a version or range like >=1.0")
            clean_requires[key] = value
    if "asset_types" in requires:
        clean_requires["asset_types"] = _words(requires["asset_types"], "[requires] asset_types")
    if "roles" in requires:
        roles = requires["roles"]
        if not isinstance(roles, dict) or len(roles) > 50:
            raise PackageError("[requires] roles: a table of asset type = [roles]")
        for kind, names in roles.items():
            if not WORD.match(kind):
                raise PackageError("[requires] roles: invalid asset type")
            _words(names, f"[requires] roles.{kind}")
        clean_requires["roles"] = {kind: list(names) for kind, names in roles.items()}
    suggests = _section(manifest, "suggests")
    clean = {
        "format": FORMAT,
        "app": {
            "id": app_id,
            "name": _text(app.get("name"), "[app] name", 60),
            "version": version,
            "category": _text(app.get("category"), "[app] category", 80, required=False),
            "summary": _text(app.get("summary"), "[app] summary", 200),
            "description": _text(app.get("description"), "[app] description", 2000, required=False),
            "publisher": publisher,
            "license": _text(app.get("license"), "[app] license", 80, required=False),
            "homepage": homepage,
            "mark": mark or "",
        },
        "runtime": {"prefix": prefix, "port": port, "uid": uid, "health": health, "image": app_id},
        "requires": clean_requires,
        "permissions": {
            "read": _words(permissions.get("read"), "[permissions] read", allowed=READ_SCOPES),
            "write": _words(permissions.get("write"), "[permissions] write", allowed=WRITE_SCOPES),
            "plant_write": False,
            "outbound": [],
        },
        "publishes": _links(_section(manifest, "publishes"), "publishes"),
        "consumes": _links(_section(manifest, "consumes"), "consumes"),
        "suggests": {"asset_types": _words(suggests["asset_types"], "[suggests] asset_types")}
        if "asset_types" in suggests
        else {},
    }
    if "backup" in manifest:
        clean["backup"] = _backup(_section(manifest, "backup"))
    if "contributes" in manifest:
        clean["contributes"] = _contributes(_section(manifest, "contributes"))
    added = [clean.get("contributes", {}), clean["publishes"].get("series", [])]
    if len(json.dumps(added)) > CONTRIBUTES_BYTES:
        raise PackageError(
            f"[contributes] and [[publishes.series]]: at most {CONTRIBUTES_BYTES} bytes"
        )
    if with_files:
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(PAYLOAD):
            raise PackageError(f"files: exactly {list(PAYLOAD)}")
        for name, entry in files.items():
            if not isinstance(entry, dict) or set(entry) != {"sha256", "size"}:
                raise PackageError(f'files.{name}: {{"sha256": ..., "size": ...}}')
            if not isinstance(entry["sha256"], str) or not HEX64.match(entry["sha256"]):
                raise PackageError(f"files.{name}.sha256: 64 lower-case hex digits")
            if (
                not isinstance(entry["size"], int)
                or isinstance(entry["size"], bool)
                or entry["size"] < 0
            ):
                raise PackageError(f"files.{name}.size: a number of bytes")
        clean["files"] = {name: dict(files[name]) for name in PAYLOAD}
    return clean


def image_ref(manifest: dict[str, Any]) -> str:
    """The one tag a package's image.tar carries: ``<runtime.image>:<app.version>``."""

    return f"{manifest['runtime']['image']}:{manifest['app']['version']}"


def permission_ids(manifest: dict[str, Any]) -> list[str]:
    granted = manifest.get("permissions") or {}
    return [f"read.{name}" for name in granted.get("read") or []] + [
        f"write.{name}" for name in granted.get("write") or []
    ]


def flat(manifest: dict[str, Any]) -> dict[str, Any]:
    """One level view of a validated manifest, the shape the installer and the page use."""

    app, runtime = manifest["app"], manifest["runtime"]
    return {
        "id": app["id"],
        "name": app["name"],
        "version": app["version"],
        "category": app["category"],
        "summary": app["summary"],
        "description": app["description"],
        "license": app["license"],
        "homepage": app["homepage"],
        "publisher": {"id": publisher_id(app["publisher"]), "name": app["publisher"]},
        "prefix": runtime["prefix"],
        "port": runtime["port"],
        "uid": runtime["uid"],
        "health": runtime["health"],
        "image": image_ref(manifest),
        "permissions": permission_ids(manifest),
        "plant_write": False,
        "outbound": [],
        "requires": manifest["requires"],
        "publishes": manifest["publishes"],
        "consumes": manifest["consumes"],
        "suggests": manifest["suggests"],
        "contributes": manifest.get("contributes", {}),
        "adds": adds(manifest),
    }


def adds(manifest: dict[str, Any]) -> dict[str, int]:
    """How many of each thing the app adds to PlantCraft, for the page that shows the package."""

    counts = {
        key: len(value)
        for key, value in (manifest.get("contributes") or {}).items()
        if isinstance(value, list) and value
    }
    contributes = manifest.get("contributes") or {}
    for key in ("search", "queue"):
        if contributes.get(key):
            counts[key] = 1
    series = (manifest.get("publishes") or {}).get("series") or []
    if series:
        counts["series"] = len(series)
    return counts


def from_app_toml(data: bytes) -> dict[str, Any]:
    """The manifest template (no ``files``) from an app repository's ``app.toml``."""

    import tomllib

    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PackageError(f"app.toml is not valid TOML: {exc}") from exc
    template = {name: document[name] for name in SECTIONS if name in document}
    unknown = sorted(set(document) - set(SECTIONS))
    if unknown:
        raise PackageError(f"app.toml: unknown sections {unknown}")
    return {**template, "format": FORMAT}


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """How a manifest is written in a package (the bytes the signature covers)."""

    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


# SBOM ---------------------------------------------------------------------------------------


def sbom_summary(data: bytes) -> dict[str, Any]:
    """What the administrator sees before confirming: format, name and the components."""

    document = strict_json(data, SBOM)
    if not isinstance(document, dict):
        raise PackageError("sbom.spdx.json must be a JSON object")
    version = document.get("spdxVersion")
    if not isinstance(version, str) or not version.startswith("SPDX-"):
        raise PackageError("sbom.spdx.json is not an SPDX document (spdxVersion missing)")
    packages = document.get("packages", [])
    if not isinstance(packages, list):
        raise PackageError("sbom.spdx.json: packages must be a list")
    components = []
    for item in packages:
        if not isinstance(item, dict):
            continue
        license_ = item.get("licenseConcluded") or item.get("licenseDeclared") or ""
        components.append(
            {
                "name": str(item.get("name") or "")[:200],
                "version": str(item.get("versionInfo") or "")[:100],
                "license": str(license_)[:200],
            }
        )
    created = document.get("creationInfo", {})
    return {
        "format": version[:20],
        "name": str(document.get("name") or "")[:200],
        "created": str(created.get("created") or "")[:40] if isinstance(created, dict) else "",
        "packages": len(components),
        "components": components[:500],
    }


# Reading a package --------------------------------------------------------------------------


@dataclass
class VerifiedPackage:
    manifest: dict[str, Any]
    manifest_raw: bytes
    signature: bytes
    publisher: dict[str, str]
    sbom: dict[str, Any]
    sbom_raw: bytes
    image_ids: tuple[str, ...]
    sha256: str
    size: int
    files: dict[str, dict[str, Any]] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        view = flat(self.manifest)
        return {
            **view,
            "image_id": self.image_ids[-1],
            "image_ids": list(self.image_ids),
            "publisher": self.publisher,
            "permissions": [{"id": p, "label": PERMISSIONS[p]} for p in view["permissions"]],
            "files": self.files,
            "sha256": self.sha256,
            "size": self.size,
        }


class _Tee(io.RawIOBase):
    """Reads ``source`` up to ``limit`` bytes, hashing everything and copying it to ``sink``."""

    def __init__(self, source: IO[bytes], limit: int, sink: IO[bytes] | None = None):
        self.source, self.limit, self.sink = source, limit, sink
        self.hash = hashlib.sha256()
        self.count = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        data = self.source.read(min(len(buffer), CHUNK))
        if not data:
            return 0
        self.count += len(data)
        if self.count > self.limit:
            raise PackageError("a file in the package is larger than it says")
        self.hash.update(data)
        if self.sink is not None:
            self.sink.write(data)
        buffer[: len(data)] = data
        return len(data)

    def drain(self) -> None:
        while self.readinto(bytearray(CHUNK)):
            pass


def _normal_ref(name: str) -> str:
    for prefix in ("docker.io/library/", "docker.io/"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


@dataclass(frozen=True)
class ImageArchive:
    # The image configuration digest, then the digests of the index manifests: `docker image
    # inspect` reports one of them as the id, depending on the daemon's image store.
    ids: tuple[str, ...]
    names: tuple[str, ...]

    @property
    def image_id(self) -> str:
        return self.ids[-1]


def read_image_archive(stream: IO[bytes]) -> ImageArchive:
    """Reads a ``docker save`` stream: its one image's id and every name it would tag."""

    meta: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for count, member in enumerate(archive, start=1):
                if count > IMAGE_MAX_MEMBERS:
                    raise PackageError("image.tar has too many entries")
                if member.name in IMAGE_META and member.isreg():
                    if member.size > IMAGE_META_LIMIT:
                        raise PackageError(f"image.tar: {member.name} is too large")
                    handle = archive.extractfile(member)
                    meta[member.name] = handle.read(IMAGE_META_LIMIT + 1) if handle else b""
    except PackageError:
        raise
    except (tarfile.TarError, EOFError, OSError, ValueError) as exc:
        raise PackageError(f"image.tar is not an image archive (docker save): {exc}") from exc
    if "manifest.json" not in meta:
        raise PackageError("image.tar has no manifest.json: build it with docker save")
    entries = strict_json(meta["manifest.json"], "image.tar manifest.json")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise PackageError("image.tar must hold exactly one image")
    tags = entries[0].get("RepoTags")
    if not isinstance(tags, list) or not tags:
        raise PackageError("image.tar: the image has no tag (docker save <name>:<version>)")
    names = [_normal_ref(str(tag)) for tag in tags]
    digest = re.fullmatch(
        r"(?:blobs/sha256/)?([0-9a-f]{64})(?:\.json)?", str(entries[0].get("Config") or "")
    )
    if not digest:
        raise PackageError("image.tar: unknown image configuration")
    ids = [f"sha256:{digest.group(1)}"]
    if "index.json" in meta:
        index = strict_json(meta["index.json"], "image.tar index.json")
        manifests = index.get("manifests", []) if isinstance(index, dict) else None
        if not isinstance(manifests, list):
            raise PackageError("image.tar: index.json is malformed")
        for item in manifests:
            if isinstance(item, dict) and re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(item.get("digest"))
            ):
                ids.append(str(item["digest"]))
            annotations = item.get("annotations", {}) if isinstance(item, dict) else {}
            if isinstance(annotations, dict) and "io.containerd.image.name" in annotations:
                names.append(_normal_ref(str(annotations["io.containerd.image.name"])))
    if "repositories" in meta:
        repositories = strict_json(meta["repositories"], "image.tar repositories")
        if not isinstance(repositories, dict):
            raise PackageError("image.tar: repositories is malformed")
        for repo, repo_tags in repositories.items():
            for tag in repo_tags if isinstance(repo_tags, dict) else {}:
                names.append(_normal_ref(f"{repo}:{tag}"))
    return ImageArchive(tuple(ids), tuple(names))


def check_image_names(archive: ImageArchive, image: str) -> None:
    """Loading the archive must tag ``image`` and nothing else (never another app's image)."""

    others = sorted(set(archive.names) - {image})
    if image not in archive.names or others:
        raise PackageError(
            f"image.tar must be tagged {image} and nothing else (found {sorted(set(archive.names))})"
        )


def _file_digest(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _open_private(path: Path) -> IO[bytes]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(path, flags, 0o640), "wb")


def verify_package(
    path: str | Path,
    trusted: dict[str, Ed25519PublicKey],
    *,
    extract_to: str | Path | None = None,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> VerifiedPackage:
    """Every check of docs/app-package.md; raises PackageError with the reason.

    With ``extract_to`` (an empty folder the caller owns), ``image.tar`` and
    ``sbom.spdx.json`` are written there while they are hashed, so what is used
    afterwards is exactly what was verified.
    """

    path = Path(path)
    out = Path(extract_to) if extract_to is not None else None
    if not path.is_file():
        raise PackageError("the package file is missing")
    package_sha, package_size = _file_digest(path)
    limits = {**LIMITS, IMAGE: max_image_bytes}
    small: dict[str, bytes] = {}
    hashes: dict[str, tuple[str, int]] = {}
    image: ImageArchive | PackageError = PackageError("image.tar is missing")
    seen: set[str] = set()
    try:
        with tarfile.open(path, mode="r|*") as archive:
            for count, member in enumerate(archive, start=1):
                if count > len(MEMBERS):
                    raise PackageError(
                        f"the package holds more than the {len(MEMBERS)} files it may"
                    )
                name = member.name
                if name not in MEMBERS:
                    raise PackageError(
                        f"unexpected entry {name[:80]!r}: a package holds only {list(MEMBERS)}"
                    )
                if name in seen:
                    raise PackageError(f"{name} appears twice")
                seen.add(name)
                if not member.isreg():
                    raise PackageError(
                        f"{name} must be a regular file (no links, folders or devices)"
                    )
                if member.size > limits[name]:
                    raise PackageError(f"{name} is larger than {limits[name] // MiB or 1} MiB")
                handle = archive.extractfile(member)
                if handle is None:
                    raise PackageError(f"{name} cannot be read")
                if name in (MANIFEST, SIGNATURE):
                    small[name] = handle.read(limits[name] + 1)
                    continue
                sink = _open_private(out / name) if out is not None else None
                try:
                    tee = _Tee(handle, limits[name], sink)
                    if name == SBOM:
                        small[name] = tee.read()  # type: ignore[assignment]
                    else:
                        reader = io.BufferedReader(tee, buffer_size=CHUNK)
                        try:
                            image = read_image_archive(reader)
                        except PackageError as exc:
                            image = exc
                        tee.drain()
                    hashes[name] = (tee.hash.hexdigest(), tee.count)
                finally:
                    if sink is not None:
                        sink.close()
    except PackageError:
        _clean(out)
        raise
    except (tarfile.TarError, EOFError, OSError, ValueError, zlib.error) as exc:
        _clean(out)
        raise PackageError(f"not a readable package (tar): {exc}") from exc
    try:
        return _check(small, hashes, trusted, package_sha, package_size, image)
    except PackageError:
        _clean(out)
        raise


def _clean(out: Path | None) -> None:
    if out is None:
        return
    for name in PAYLOAD:
        try:
            (out / name).unlink()
        except OSError:
            pass


def trusted_key(document: Any, trusted: dict[str, Ed25519PublicKey]) -> Ed25519PublicKey:
    """The trusted key of the publisher a manifest names (before its signature is checked)."""

    app = document.get("app") if isinstance(document, dict) else None
    name = app.get("publisher") if isinstance(app, dict) else None
    if not isinstance(name, str) or not PUBLISHER_NAME.match(name):
        raise PackageError("manifest.json names no valid publisher")
    key = trusted.get(publisher_id(name))
    if key is None:
        raise PackageError(
            f"unknown publisher {name!r}: {publisher_id(name)}.pub is not among the trusted publishers"
        )
    return key


def _check(
    small: dict[str, bytes],
    hashes: dict[str, tuple[str, int]],
    trusted: dict[str, Ed25519PublicKey],
    package_sha: str,
    package_size: int,
    image: ImageArchive | PackageError,
) -> VerifiedPackage:
    missing = [name for name in MEMBERS if name not in small and name not in hashes]
    if missing:
        raise PackageError(f"the package is missing {missing}")
    raw, signature = small[MANIFEST], small[SIGNATURE]
    key = trusted_key(strict_json(raw, MANIFEST), trusted)
    verify_signature(raw, signature, key)
    document = strict_json(raw, MANIFEST)
    manifest = validate_manifest(document)
    for name in PAYLOAD:
        expected = manifest["files"][name]
        digest, size = hashes[name]
        if digest != expected["sha256"] or size != expected["size"]:
            raise PackageError(f"{name} does not match its SHA-256 in the manifest")
    if isinstance(image, PackageError):
        raise image
    check_image_names(image, image_ref(manifest))
    sbom = sbom_summary(small[SBOM])
    return VerifiedPackage(
        manifest=manifest,
        manifest_raw=raw,
        signature=signature,
        publisher={**flat(manifest)["publisher"], "key_id": key_id(key)},
        sbom=sbom,
        sbom_raw=small[SBOM],
        image_ids=image.ids,
        sha256=package_sha,
        size=package_size,
        files={name: manifest["files"][name] for name in PAYLOAD},
    )


# Building a package -------------------------------------------------------------------------


def build_package(
    template: dict[str, Any],
    image_tar: str | Path,
    sbom: str | Path,
    key_path: str | Path,
    out: str | Path,
    *,
    compress: bool = False,
) -> dict[str, Any]:
    """Writes a signed package; returns its manifest. ``template`` is the manifest without files."""

    image_tar, sbom, out = Path(image_tar), Path(sbom), Path(out)
    key = load_private_key(key_path)
    draft = {k: v for k, v in template.items() if k not in {"files", "format"}}
    draft["format"] = FORMAT
    validate_manifest(draft, with_files=False)
    sbom_summary(sbom.read_bytes())
    with image_tar.open("rb") as handle:
        check_image_names(
            read_image_archive(handle), image_ref(validate_manifest(draft, with_files=False))
        )
    files = {}
    for name, source in ((IMAGE, image_tar), (SBOM, sbom)):
        digest, size = _file_digest(source)
        files[name] = {"sha256": digest, "size": size}
    manifest = validate_manifest({**draft, "files": files})
    raw = manifest_bytes(manifest)
    signature = sign(raw, key)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".partial")
    with tarfile.open(
        partial, mode="w:gz" if compress else "w", format=tarfile.PAX_FORMAT
    ) as archive:
        for name, data in ((MANIFEST, raw), (SIGNATURE, signature)):
            info = _info(name, len(data))
            archive.addfile(info, io.BytesIO(data))
        for name, source in ((SBOM, sbom), (IMAGE, image_tar)):
            info = _info(name, source.stat().st_size)
            with source.open("rb") as handle:
                archive.addfile(info, handle)
    partial.replace(out)
    return manifest


def _info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = size, 0o644, 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def read_manifest(path: str | Path) -> dict[str, Any]:
    """The manifest of a package, unverified (for building a catalog index)."""

    with tarfile.open(path, mode="r|*") as archive:
        for member in archive:
            if member.name == MANIFEST and member.isreg() and member.size <= LIMITS[MANIFEST]:
                handle = archive.extractfile(member)
                return validate_manifest(strict_json(handle.read() if handle else b"", MANIFEST))
    raise PackageError("no manifest.json in the package")


# Catalog index ------------------------------------------------------------------------------


def build_index(
    packages: list[str | Path], key_path: str | Path, publisher: str, out_dir: str | Path
) -> Path:
    """``index.json`` and ``index.json.sig`` for an online catalog of packages."""

    if not PUBLISHER_ID.match(publisher):
        raise PackageError("publisher: 2 to 40 lower-case letters, digits or hyphens")
    key = load_private_key(key_path)
    apps = []
    for item in packages:
        path = Path(item)
        view = flat(read_manifest(path))
        digest, size = _file_digest(path)
        apps.append(
            {
                "id": view["id"],
                "name": view["name"],
                "version": view["version"],
                "summary": view["summary"],
                "description": view["description"],
                "publisher": view["publisher"],
                "package": path.name,
                "sha256": digest,
                "size": size,
            }
        )
    index = {"format": FORMAT, "publisher": publisher, "apps": apps}
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    raw = manifest_bytes(index)
    (folder / "index.json").write_bytes(raw)
    (folder / "index.json.sig").write_bytes(sign(raw, key))
    return folder / "index.json"


def verify_index(
    raw: bytes, signature: bytes, trusted: dict[str, Ed25519PublicKey]
) -> list[dict[str, Any]]:
    """The apps of a signed catalog index; raises PackageError when it cannot be trusted."""

    if len(raw) > INDEX_LIMIT:
        raise PackageError("the catalog index is too large")
    document = strict_json(raw, "index.json")
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise PackageError(f"index.json: format must be {FORMAT}")
    publisher = document.get("publisher")
    key = trusted.get(publisher) if isinstance(publisher, str) else None
    if key is None:
        raise PackageError(f"the catalog is signed by an unknown publisher ({publisher!r})")
    verify_signature(raw, signature, key)
    apps = document.get("apps")
    if not isinstance(apps, list) or len(apps) > 500:
        raise PackageError("index.json: apps must be a list of at most 500")
    clean = []
    for entry in apps:
        if not isinstance(entry, dict):
            raise PackageError("index.json: every app is an object")
        app_id, version = entry.get("id"), entry.get("version")
        package = entry.get("package")
        if not isinstance(app_id, str) or not APP_ID.match(app_id):
            raise PackageError("index.json: invalid app id")
        if not isinstance(version, str) or not VERSION.match(version):
            raise PackageError(f"index.json: invalid version for {app_id}")
        if (
            not isinstance(package, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,200}", package)
            or ".." in package
        ):
            raise PackageError(f"index.json: invalid package path for {app_id}")
        if not isinstance(entry.get("sha256"), str) or not HEX64.match(entry["sha256"]):
            raise PackageError(f"index.json: invalid sha256 for {app_id}")
        size = entry.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise PackageError(f"index.json: invalid size for {app_id}")
        entry_publisher = entry.get("publisher") if isinstance(entry.get("publisher"), dict) else {}
        clean.append(
            {
                "id": app_id,
                "name": _text(entry.get("name"), "name", 60),
                "version": version,
                "summary": _text(entry.get("summary"), "summary", 200, required=False),
                "description": _text(entry.get("description"), "description", 2000, required=False),
                "publisher": {
                    "id": str(entry_publisher.get("id") or publisher)[:40],
                    "name": str(entry_publisher.get("name") or "")[:120],
                },
                "package": package,
                "sha256": entry["sha256"],
                "size": size,
            }
        )
    return clean


# Command line -------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="package.py", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("keygen", help="new publisher key pair (<name>.key, <name>.pub)")
    gen.add_argument("--name", required=True)
    gen.add_argument("--out-dir", required=True)
    build = commands.add_parser("build", help="build and sign a package")
    build.add_argument(
        "--manifest", required=True, help="the app's app.toml (or the same sections as JSON)"
    )
    build.add_argument("--image-tar", required=True, help="docker save output of the one image")
    build.add_argument("--sbom", required=True, help="SPDX JSON SBOM of the image")
    build.add_argument("--key", required=True, help="publisher private key (PEM), never committed")
    build.add_argument("--out", required=True)
    build.add_argument("--gzip", action="store_true", help="compress the package")
    check = commands.add_parser("verify", help="verify a package against trusted publisher keys")
    check.add_argument("--trusted", required=True, help="folder of <publisher>.pub files")
    check.add_argument("package")
    index = commands.add_parser("index", help="sign a catalog index of packages")
    index.add_argument("--key", required=True)
    index.add_argument("--publisher", required=True)
    index.add_argument("--out-dir", required=True)
    index.add_argument("packages", nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            private, public = keygen(args.name, args.out_dir)
            print(f"private key: {private} (keep it secret, never commit it)")
            print(f"public key:  {public} (copy it to trusted-publishers/{args.name}.pub)")
        elif args.command == "build":
            source = Path(args.manifest).read_bytes()
            if args.manifest.endswith(".toml"):
                template = from_app_toml(source)
            else:
                template = strict_json(source, args.manifest)
            if not isinstance(template, dict):
                raise PackageError("the manifest must be a JSON object")
            manifest = build_package(
                template, args.image_tar, args.sbom, args.key, args.out, compress=args.gzip
            )
            print(
                f"{args.out}: {manifest['app']['id']} {manifest['app']['version']} "
                f"signed by {manifest['app']['publisher']}"
            )
        elif args.command == "verify":
            verified = verify_package(args.package, load_trusted(args.trusted))
            print(json.dumps(verified.summary(), indent=2))
        elif args.command == "index":
            path = build_index(args.packages, args.key, args.publisher, args.out_dir)
            print(f"{path} and {path}.sig written")
    except (PackageError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
